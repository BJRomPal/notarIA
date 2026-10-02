# Despliegue de la beta en GCP

> **Estado: en ejecución.** Ya corrieron contra el proyecto real los pasos 0, 1, 2.2 y el build de
> las imágenes (2026-10-01); lo demás sigue sin ejecutarse y sale de la documentación de Google.
> Donde algo falle, corregirlo acá. Un ajuste que ya hizo falta: Cloud Build necesita una cuenta de
> servicio propia (paso 1), porque la cuenta por defecto no trae permisos.

La beta se publica en **https://chatnotarial.ar**. Todo va en **`us-central1`**, la misma región
que el grafo en Aura Professional (Aura Pro en GCP no está en Sudamérica). Desde Buenos Aires son
~30 ms más que us-east1, y eso no se nota contra un turno de 10 a 30 s.

```
escribano ──► chatnotarial.ar ──► balanceador HTTPS (IP fija, certificado de Google)
                                     │
                                     ▼
                            IAP ──► Cloud Run «notaria» (1 instancia, solo acepta el balanceador)
                                     ├─ web  Next, puerto 3000 ── /api ──┐
                                     └─ api  FastAPI, puerto 8000 ◄──────┘ localhost
                                              ├─► Cloud SQL Postgres 16  (socket /cloudsql)
                                              ├─► Aura Professional       (neo4j+s://)
                                              └─► Gemini
```

**Por qué un balanceador y no el mapeo de dominio de Cloud Run**, que es gratis: el mapeo está en
preview y Google lo desaconseja para producción. El balanceador es la opción recomendada y cuesta
unos US$18 por mes. IAP queda activado sobre el servicio, no sobre el balanceador (no se puede en
los dos), y protege también lo que entra por él.

## Una sola vez

### 0. Variables

```bash
export PROYECTO=notaria-beta            # el id del proyecto
export REGION=us-central1
export DOMINIO=chatnotarial.ar
gcloud config set project $PROYECTO
export NUMERO_PROYECTO=$(gcloud projects describe $PROYECTO --format='value(projectNumber)')
```

### 1. Presupuesto y APIs

```bash
gcloud billing budgets create --billing-account=<CUENTA> --display-name="NotarIA beta" \
  --budget-amount=250USD --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0

gcloud services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com iap.googleapis.com \
  compute.googleapis.com dns.googleapis.com

gcloud artifacts repositories create notaria --repository-format=docker --location=$REGION

# La cuenta con la que Cloud Build construye las imágenes. Por defecto usa la cuenta de servicio de
# Compute, y en una organización con las políticas de seguridad por defecto esa cuenta no tiene
# ningún rol: el build falla al leer el código que se acaba de subir (403 storage.objects.get).
gcloud iam service-accounts create notaria-build --display-name="NotarIA: construir imágenes"
sleep 30   # la cuenta tarda unos segundos en existir para IAM; sin esto el binding falla
gcloud projects add-iam-policy-binding $PROYECTO --condition=None \
  --member=serviceAccount:notaria-build@$PROYECTO.iam.gserviceaccount.com \
  --role=roles/cloudbuild.builds.builder
```

### 2. Dominio: arrancarlo primero, es lo que más tarda

La delegación en NIC Argentina y el certificado pueden tardar hasta un día cada uno.

**2.1. Que el dominio esté vigente.** En [nic.ar](https://nic.ar), con CUIT y clave fiscal, ir a
*Mis dominios*. `chatnotarial.ar` tiene que figurar a tu nombre y pago. Si figura pendiente de
pago o de alta, eso se resuelve primero: sin eso no se puede delegar.

**2.2. La zona DNS en Google y la IP fija del balanceador.**

```bash
gcloud dns managed-zones create chatnotarial --dns-name=$DOMINIO. --description="NotarIA beta"

gcloud compute addresses create notaria-ip --global --ip-version=IPV4 --network-tier=PREMIUM
export IP=$(gcloud compute addresses describe notaria-ip --global --format='get(address)')

gcloud dns record-sets create $DOMINIO.     --zone=chatnotarial --type=A --ttl=300 --rrdatas=$IP
gcloud dns record-sets create www.$DOMINIO. --zone=chatnotarial --type=A --ttl=300 --rrdatas=$IP

# Los cuatro servidores que hay que cargar en NIC Argentina:
gcloud dns managed-zones describe chatnotarial --format='value(nameServers)'
```

**2.3. Delegar en NIC Argentina.** En nic.ar → *Trámites a Distancia* → *Operaciones sobre
dominios* → buscar `chatnotarial.ar` → **Delegar** → *Agregar una nueva delegación*, una vez por
cada uno de los cuatro servidores del paso anterior (`ns-cloud-xN.googledomains.com.`). Van sin
IP y **sin** tildar «Autodelegar», porque los servidores no están dentro del dominio. El trámite
no tiene costo.

Para saber si ya quedó:

```bash
dig NS chatnotarial.ar +short          # tienen que aparecer los ns-cloud-* de Google
dig A  chatnotarial.ar +short          # tiene que dar $IP
```

### 3. Grafo: Aura Professional, una COPIA congelada

**La ingesta sigue en la instancia Aura actual y nunca en la de la beta.** La Pro es una copia
que no cambia mientras dura la beta: si cambiara, cambiarían las respuestas a mitad de la
evaluación y las notas de antes y de después dejarían de ser comparables. Si hace falta llevar
normas nuevas a la beta, se vuelve a copiar la instancia actual sobre la Pro, y ese día se anota,
porque parte el análisis en dos.

1. En la consola de Aura, crear una instancia **Professional en GCP `us-central1`, 1 GB**.
2. Cargarla clonando la instancia actual o restaurando el último backup de `DBbackups/`.
3. Verificar contra la Pro, con su URI y sus credenciales en un `.env` aparte:
   - `.venv/bin/python tests/test_api_catalogo.py`: los conteos tienen que coincidir con los de
     la instancia actual.
   - `SHOW INDEXES`: `index_articulos` e `index_jurisprudencia` en estado `ONLINE`.
   - `.venv/bin/python tests/test_jurisprudencia.py --recuperacion`: el mismo resultado que con
     la instancia actual. No llama a ningún LLM.
4. Si Aura muestra presión de memoria, se redimensiona a 2 GB sin cortar el servicio.

**Cuidado con la instancia actual, que es Free.** Aura la pausa a las 72 horas sin actividad y,
[según su documentación](https://neo4j.com/docs/aura/managing-instances/instance-actions/), **si
queda pausada más de 30 días la borra con todos sus datos**, sin recuperación. Como ahora es la
base de ingesta:
- sacar un backup a `DBbackups/` después de cada ingesta;
- no dejarla pausada más de un par de semanas: reanudarla desde la consola alcanza.

Sigue sin haber rol de solo lectura en ninguna de las dos (existe recién en Business Critical):
la API usa las credenciales admin, y el Text-to-Cypher corre en `execute_read`.

### 4. Postgres: Cloud SQL

```bash
gcloud sql instances create notaria-pg --database-version=POSTGRES_16 --edition=ENTERPRISE \
  --tier=db-g1-small --region=$REGION --storage-size=10 \
  --backup-start-time=06:00 --enable-point-in-time-recovery
gcloud sql databases create notaria --instance=notaria-pg
gcloud sql users create notaria --instance=notaria-pg --password=<CLAVE>
```

Las migraciones se cargan desde la GX10 **en orden**, con el
[Cloud SQL Auth Proxy](https://cloud.google.com/sql/docs/postgres/sql-proxy) (tiene binario arm64):

```bash
./cloud-sql-proxy $PROYECTO:$REGION:notaria-pg --port 5433 &
URL="postgresql://notaria:<CLAVE>@localhost:5433/notaria"
for f in db/0*.sql; do
  echo "==> $f"
  docker run --rm -i --network host postgres:16 psql "$URL" -v ON_ERROR_STOP=1 -q < "$f"
done
```

Las tablas del checkpointer de LangGraph no se cargan a mano: las crea la API al arrancar.

### 5. Secretos y cuenta de servicio

```bash
for s in NEO4J_URI NEO4J_USERNAME NEO4J_PASSWORD GOOGLE_API_KEY TELEGRAM_TOKEN TELEGRAM_CHAT_ID; do
  read -rsp "$s: " v; echo
  printf '%s' "$v" | gcloud secrets create $s --data-file=-
done
printf '%s' "postgresql://notaria:<CLAVE>@/notaria?host=/cloudsql/$PROYECTO:$REGION:notaria-pg" \
  | gcloud secrets create POSTGRES_URL --data-file=-

gcloud iam service-accounts create notaria-run
for r in roles/secretmanager.secretAccessor roles/cloudsql.client; do
  gcloud projects add-iam-policy-binding $PROYECTO \
    --member=serviceAccount:notaria-run@$PROYECTO.iam.gserviceaccount.com --role=$r
done
```

Los `NEO4J_*` son los de la instancia **Pro**, no los de la actual.

**Gemini: la clave tiene que ser de un proyecto con facturación.** En el nivel gratuito, Google
puede usar el contenido de las consultas para mejorar sus productos, y en la beta esas consultas
son de escribanos reales.

### 6. El cliente OAuth de IAP, para cuentas de afuera de la organización

Los escribanos entran con su cuenta de Google (Gmail o cualquier mail registrado como cuenta de
Google). El cliente OAuth que administra Google **solo deja entrar a usuarios de la misma
organización**, así que hace falta uno propio:

1. Consola → Google Auth Platform → *Branding*: nombre «NotarIA», mail de soporte y, como página
   de la app, `https://chatnotarial.ar`, con `chatnotarial.ar` en *Authorized domains*. En
   *Audience*: **External**, y publicar la app. Con los permisos básicos que pide IAP (openid,
   email) no hace falta verificación.
2. *Clients* → crear un cliente OAuth de tipo *Web application*, con este URI de redirección:
   `https://iap.googleapis.com/v1/oauth/clientIds/<CLIENT_ID>:handleRedirect`.

Se le asigna al servicio en el paso 8, cuando el servicio ya existe.

### 7. Primer deploy

El de la sección [Cada deploy](#cada-deploy). El servicio queda arriba pero todavía no se lo puede
alcanzar: solo acepta tráfico del balanceador, que se arma en el paso siguiente.

### 8. Balanceador, certificado e IAP

```bash
# Cloud Run como backend del balanceador.
gcloud compute network-endpoint-groups create notaria-neg --region=$REGION \
  --network-endpoint-type=serverless --cloud-run-service=notaria
gcloud compute backend-services create notaria-backend --global \
  --load-balancing-scheme=EXTERNAL_MANAGED
gcloud compute backend-services add-backend notaria-backend --global \
  --network-endpoint-group=notaria-neg --network-endpoint-group-region=$REGION
gcloud compute url-maps create notaria-urlmap --default-service=notaria-backend

# HTTPS con certificado administrado por Google, para el dominio y www.
gcloud compute ssl-certificates create notaria-cert --global --domains=$DOMINIO,www.$DOMINIO
gcloud compute target-https-proxies create notaria-https --url-map=notaria-urlmap \
  --ssl-certificates=notaria-cert
gcloud compute forwarding-rules create notaria-443 --global --address=notaria-ip --ports=443 \
  --load-balancing-scheme=EXTERNAL_MANAGED --network-tier=PREMIUM --target-https-proxy=notaria-https

# http:// redirige a https://. Entra en las primeras cinco reglas, que se cobran juntas.
gcloud compute url-maps import notaria-redirect --global --source=/dev/stdin <<EOF
name: notaria-redirect
defaultUrlRedirect:
  httpsRedirect: true
  redirectResponseCode: MOVED_PERMANENTLY_DEFAULT
EOF
gcloud compute target-http-proxies create notaria-http --url-map=notaria-redirect
gcloud compute forwarding-rules create notaria-80 --global --address=notaria-ip --ports=80 \
  --load-balancing-scheme=EXTERNAL_MANAGED --network-tier=PREMIUM --target-http-proxy=notaria-http

# IAP con el cliente OAuth del paso 6, y permiso para que IAP invoque el servicio.
cat > /tmp/iap-oauth.yaml <<EOF
accessSettings:
  oauthSettings:
    clientId: <CLIENT_ID>
    clientSecret: <CLIENT_SECRET>
EOF
gcloud iap settings set /tmp/iap-oauth.yaml --project=$PROYECTO \
  --resource-type=cloud-run --region=$REGION --service=notaria
gcloud run services add-iam-policy-binding notaria --region=$REGION \
  --member=serviceAccount:service-$NUMERO_PROYECTO@gcp-sa-iap.iam.gserviceaccount.com \
  --role=roles/run.invoker
```

El certificado se emite recién cuando `chatnotarial.ar` ya resuelve a la IP del balanceador
(paso 2), y puede tardar hasta 24 horas. Para seguirlo:

```bash
gcloud compute ssl-certificates describe notaria-cert --global \
  --format='get(managed.status, managed.domainStatus)'     # hasta que diga ACTIVE
```

## Cada deploy

Desde la raíz y con el árbol limpio: la versión es el SHA y queda en cada turno de la beta.

```bash
export VERSION=$(git rev-parse --short HEAD)
test -z "$(git status --porcelain)" || echo "HAY CAMBIOS SIN COMMITEAR: la versión no los describe"

gcloud builds submit --config cloudbuild.yaml --substitutions=_VERSION=$VERSION \
  --service-account=projects/$PROYECTO/serviceAccounts/notaria-build@$PROYECTO.iam.gserviceaccount.com

envsubst '${PROYECTO} ${NUMERO_PROYECTO} ${VERSION}' < deploy/servicio.yaml > /tmp/servicio.yaml
gcloud run services replace /tmp/servicio.yaml --region=$REGION
```

`services replace` no toca los permisos ni el balanceador, así que la regla de invocación de IAP y
el dominio se mantienen.

## Quién entra: la lista de la beta

Cada escribano es una línea. Esa lista **es** la beta:

```bash
gcloud iap web add-iam-policy-binding --member=user:<MAIL> \
  --role=roles/iap.httpsResourceAccessor \
  --region=$REGION --resource-type=cloud-run --service=notaria
```

## Verificar, con el certificado ya activo

- `https://chatnotarial.ar/api/health` tiene que devolver `"autenticacion": true` y
  `"base": true`. Si `autenticacion` es `false`, falta `IAP_AUDIENCE` y todo se atribuye al
  usuario de desarrollo.
- `http://chatnotarial.ar` redirige a `https://`.
- La URL `*.run.app` del servicio ya no responde: solo se entra por el dominio.
- Una cuenta que no está en la lista queda frenada por IAP.
- Una cuenta de la lista completa una consulta y **la línea de tiempo avanza de a pasos mientras
  el agente trabaja**. Si todo aparece de golpe al final, algo en el camino está acumulando el
  stream en vez de reenviarlo.
- La consulta y la encuesta, cuando aparezca, se ven en Cloud SQL:
  `SELECT * FROM notaria.v_beta ORDER BY creado_en DESC LIMIT 5`.

## Costos estimados por mes

| Recurso | Costo |
|---|---|
| Aura Pro 1 GB | ~US$66 (2 GB: ~US$131) |
| Cloud SQL `db-g1-small` + 10 GB | ~US$27 |
| Cloud Run, 1 instancia mínima | ~US$15-35 |
| Balanceador (reglas 443 y 80) | ~US$18 más el tráfico |
| Cloud DNS, Artifact Registry, Secret Manager y Cloud Build | < US$5 |
| Gemini | por uso: `notaria.llamadas_llm` lo mide por turno |

El dominio `.ar` se paga aparte, en NIC Argentina.

## Analizar la beta

```bash
./cloud-sql-proxy $PROYECTO:$REGION:notaria-pg --port 5433 &
POSTGRES_URL="postgresql://notaria:<CLAVE>@localhost:5433/notaria" \
  .venv/bin/python exploration/exportar_beta.py
```

Deja `turnos.csv` y `turnos.jsonl` en `logs/beta_<fecha>/`. Esa carpeta no se versiona: son
consultas reales de colegas.

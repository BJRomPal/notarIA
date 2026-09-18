"use client";

// CÓMO PREGUNTARLE A NOTARIA.
//
// Contenido estático y no traído de la API: no cambia por usuario ni por sesión, y un fetch para
// mostrar texto fijo es una llamada de más y un modo de falla nuevo.
//
// Lo que hace útil a esta guía es que dice cosas que el usuario NO puede adivinar mirando la
// pantalla: que los cálculos los hace el código y no el modelo, que hay que transcribir los
// números literalmente, que el corpus cubre nueve ramas y nada más, y —sobre todo— que para saber
// qué está cargado hay que ir al inventario y no preguntárselo al agente. Ese último punto no es
// una preferencia de estilo: hoy el clasificador manda «¿tenés cargada la Ley 25.326?» a la ruta
// particular, que busca artículos parecidos y contesta sobre ellos con total seguridad.

import { Modal } from "./Modal";

function Punto({ n, titulo, children }: { n: number; titulo: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-slate-100 pt-4 first:border-0 first:pt-0">
      <h3 className="flex items-baseline gap-2 font-serif text-sm font-bold text-brand-900">
        <span className="text-accent-500">{n}.</span>
        {titulo}
      </h3>
      <div className="mt-1.5 space-y-2 text-sm leading-relaxed text-slate-600">{children}</div>
    </section>
  );
}

function Bien({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex gap-2">
      <span className="shrink-0 text-emerald-500">✓</span>
      <em className="text-slate-700 not-italic">{children}</em>
    </p>
  );
}

function Mal({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex gap-2">
      <span className="shrink-0 text-red-400">✗</span>
      <em className="text-slate-500 not-italic line-through">{children}</em>
    </p>
  );
}

export function GuiaPrompts({
  abierto,
  onCerrar,
  onVerInventario,
}: {
  abierto: boolean;
  onCerrar: () => void;
  onVerInventario: () => void;
}) {
  return (
    <Modal
      abierto={abierto}
      onCerrar={onCerrar}
      titulo="Cómo preguntarle a NotarIA"
      bajada="Siete cosas que conviene saber para sacarle mejores respuestas."
      ancho="max-w-2xl"
    >
      <div className="space-y-4">
        <Punto n={1} titulo="Preguntá como a un colega, no como a un buscador">
          <p>El sistema entiende una consulta completa; no hace falta que adivines palabras clave.</p>
          <Bien>¿Qué requisitos exige el art. 77 de la Ley 19.550 para la fusión?</Bien>
          <Mal>fusion sociedades requisitos</Mal>
        </Punto>

        <Punto n={2} titulo="Si sabés el artículo, nombralo. Si no, describí el instituto">
          <p>Son dos caminos distintos y los dos funcionan.</p>
          <Bien>¿Qué dice el art. 2.° de la Ley 17.801 sobre los documentos inscribibles?</Bien>
          <Bien>¿Cuáles son las diferencias entre la SA y la SRL?</Bien>
        </Punto>

        <Punto n={3} titulo="Para los cálculos, dictá los datos tal como los tenés">
          <p>
            Hay siete calculadoras exactas: dígito verificador de partida, CUIL, vencimiento de
            certificado, plazo de ingreso al RPI, prórroga de inscripción, porciones hereditarias
            de una sucesión intestada e Impuesto a la Transmisión Gratuita de Bienes (ITGB) de la
            Provincia de Buenos Aires.{" "}
            <strong className="font-semibold text-brand-900">
              La cuenta la hace el código, no el modelo.
            </strong>
          </p>
          <p>
            Transcribí los números como están en tu documento: si la partida tiene seis dígitos,
            poné seis; si la tenés con el cero adelante, ponelo. No los «arregles» antes de
            escribirlos.
          </p>
          <Bien>¿Cuál es el dígito verificador de la partida 164360?</Bien>
          <Bien>Certificado de dominio en CABA solicitado el 24/07/2026, ¿cuándo vence?</Bien>
          <Bien>3 hijos y cónyuge, inmueble ganancial: ¿qué fracción le corresponde a cada uno?</Bien>
          <Bien>¿Cuánto ITGB paga un hijo por una donación con valuación fiscal de $5.000.000?</Bien>
          <p className="text-slate-500">
            Podés pedir varios cálculos en una misma consulta. Para el ITGB, el parentesco tiene
            que ser uno reconocido (hijo, cónyuge, nieto, hermano, tío, sobrino, primo, sin
            parentesco, persona jurídica…); ante un vínculo distinto —hijastro, conviviente,
            yerno— el sistema te lo va a decir en vez de arriesgar una categoría.
          </p>
        </Punto>

        <Punto n={4} titulo="Repreguntá sin repetir el contexto">
          <p>
            La conversación tiene memoria. Después de preguntar por la SA,{" "}
            <em className="not-italic text-slate-700">¿y para la SRL?</em> se entiende solo.
          </p>
        </Punto>

        <Punto n={5} titulo="La jurisprudencia aparece cuando aporta">
          <p>
            No hace falta pedirla: si hay un fallo que resuelve el punto, se cita. Si querés
            forzarla, alcanza con{" "}
            <em className="not-italic text-slate-700">¿hay jurisprudencia sobre esto?</em>
          </p>
        </Punto>

        <Punto n={6} titulo="Qué hay adentro, y qué no">
          <p>
            El sistema responde sobre <strong className="font-semibold text-brand-900">derecho
            argentino</strong> en nueve ramas: civil y comercial (CCyCN), societario, registral,
            notarial, penal, tributario de CABA, financiero (UIF), datos personales y firma digital.
            Fuera de eso no hay nada cargado, y una pregunta de derecho laboral o de otra provincia
            no va a encontrar fuente.
          </p>
          <p className="rounded-xl border border-accent-500/30 bg-amber-50/70 px-3.5 py-2.5">
            Para saber si una norma puntual está cargada, usá el{" "}
            <button
              onClick={() => {
                onCerrar();
                onVerInventario();
              }}
              className="font-semibold text-accent-600 underline underline-offset-2 hover:text-accent-500"
            >
              inventario
            </button>{" "}
            y buscala por número o por nombre.{" "}
            <strong className="font-semibold text-brand-900">No se lo preguntes al agente:</strong>{" "}
            él no sabe qué tiene cargado, y ante «¿tenés la Ley 25.326?» va a buscar artículos
            parecidos y contestar sobre ellos.
          </p>
        </Punto>

        <Punto n={7} titulo="Verificá siempre contra la fuente">
          <p>
            Cada respuesta trae abajo las fuentes que la fundan.{" "}
            <strong className="font-semibold text-brand-900">Hacé clic en cualquiera:</strong> se
            abre el texto del artículo o la doctrina del fallo, con su estado de vigencia. Es la
            forma de controlar que el sistema no se desvió.
          </p>
        </Punto>
      </div>
    </Modal>
  );
}

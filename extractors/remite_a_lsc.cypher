// ============================================================
// RELACIONES REMITE_A: Ley 19550 (LSC) — remisiones internas
// Generado automáticamente escaneando articulos_lsc/
// Es idempotente: MERGE no crea duplicados si se ejecuta de nuevo.
// Total: 187 relaciones
// ============================================================

// Art. 104
MATCH (a:Articulo {id: 'Art_104_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

// Art. 110
MATCH (a:Articulo {id: 'Art_110_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

// Art. 119
MATCH (a:Articulo {id: 'Art_119_Ley_19550'})
MATCH (b:Articulo {id: 'Art_118_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 118

// Art. 128
MATCH (a:Articulo {id: 'Art_128_Ley_19550'})
MATCH (b:Articulo {id: 'Art_58_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 58

// Art. 134
MATCH (a:Articulo {id: 'Art_134_Ley_19550'})
MATCH (b:Articulo {id: 'Art_126_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 126

// Art. 136
MATCH (a:Articulo {id: 'Art_136_Ley_19550'})
MATCH (b:Articulo {id: 'Art_134_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 134

// Art. 139
MATCH (a:Articulo {id: 'Art_139_Ley_19550'})
MATCH (b:Articulo {id: 'Art_131_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 131 y 132

MATCH (a:Articulo {id: 'Art_139_Ley_19550'})
MATCH (b:Articulo {id: 'Art_132_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 131 y 132

// Art. 140
MATCH (a:Articulo {id: 'Art_140_Ley_19550'})
MATCH (b:Articulo {id: 'Art_136_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 136 y 137

MATCH (a:Articulo {id: 'Art_140_Ley_19550'})
MATCH (b:Articulo {id: 'Art_137_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 136 y 137

// Art. 145
MATCH (a:Articulo {id: 'Art_145_Ley_19550'})
MATCH (b:Articulo {id: 'Art_139_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 139

MATCH (a:Articulo {id: 'Art_145_Ley_19550'})
MATCH (b:Articulo {id: 'Art_140_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 140

// Art. 146
MATCH (a:Articulo {id: 'Art_146_Ley_19550'})
MATCH (b:Articulo {id: 'Art_150_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 150

// Art. 149
MATCH (a:Articulo {id: 'Art_149_Ley_19550'})
MATCH (b:Articulo {id: 'Art_150_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 150

MATCH (a:Articulo {id: 'Art_149_Ley_19550'})
MATCH (b:Articulo {id: 'Art_51_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 51

// Art. 150
MATCH (a:Articulo {id: 'Art_150_Ley_19550'})
MATCH (b:Articulo {id: 'Art_51_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 51

// Art. 152
MATCH (a:Articulo {id: 'Art_152_Ley_19550'})
MATCH (b:Articulo {id: 'Art_91_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 91

// Art. 156
MATCH (a:Articulo {id: 'Art_156_Ley_19550'})
MATCH (b:Articulo {id: 'Art_209_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 209

MATCH (a:Articulo {id: 'Art_156_Ley_19550'})
MATCH (b:Articulo {id: 'Art_218_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 218 y 219

MATCH (a:Articulo {id: 'Art_156_Ley_19550'})
MATCH (b:Articulo {id: 'Art_219_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 218 y 219

// Art. 157
MATCH (a:Articulo {id: 'Art_157_Ley_19550'})
MATCH (b:Articulo {id: 'Art_129_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 129

// Art. 158
MATCH (a:Articulo {id: 'Art_158_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

// Art. 159
MATCH (a:Articulo {id: 'Art_159_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

// Art. 160
MATCH (a:Articulo {id: 'Art_160_Ley_19550'})
MATCH (b:Articulo {id: 'Art_245_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 245

// Art. 161
MATCH (a:Articulo {id: 'Art_161_Ley_19550'})
MATCH (b:Articulo {id: 'Art_248_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 248

// Art. 162
MATCH (a:Articulo {id: 'Art_162_Ley_19550'})
MATCH (b:Articulo {id: 'Art_73_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 73

// Art. 166
MATCH (a:Articulo {id: 'Art_166_Ley_19550'})
MATCH (b:Articulo {id: 'Art_11_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 11

// Art. 168
MATCH (a:Articulo {id: 'Art_168_Ley_19550'})
MATCH (b:Articulo {id: 'Art_169_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 169

// Art. 169
MATCH (a:Articulo {id: 'Art_169_Ley_19550'})
MATCH (b:Articulo {id: 'Art_167_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 167

// Art. 170
MATCH (a:Articulo {id: 'Art_170_Ley_19550'})
MATCH (b:Articulo {id: 'Art_53_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 53;


// Art. 171
MATCH (a:Articulo {id: 'Art_171_Ley_19550'})
MATCH (b:Articulo {id: 'Art_168_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 168

// Art. 172
MATCH (a:Articulo {id: 'Art_172_Ley_19550'})
MATCH (b:Articulo {id: 'Art_170_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 170;

// Art. 176
MATCH (a:Articulo {id: 'Art_176_Ley_19550'})
MATCH (b:Articulo {id: 'Art_173_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 173

MATCH (a:Articulo {id: 'Art_176_Ley_19550'})
MATCH (b:Articulo {id: 'Art_175_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 175

// Art. 180
MATCH (a:Articulo {id: 'Art_180_Ley_19550'})
MATCH (b:Articulo {id: 'Art_10_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 10 y 167

MATCH (a:Articulo {id: 'Art_180_Ley_19550'})
MATCH (b:Articulo {id: 'Art_167_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 10 y 167

// Art. 184
MATCH (a:Articulo {id: 'Art_184_Ley_19550'})
MATCH (b:Articulo {id: 'Art_274_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 274

// Art. 186
MATCH (a:Articulo {id: 'Art_186_Ley_19550'})
MATCH (b:Articulo {id: 'Art_53_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 53

// Art. 187
MATCH (a:Articulo {id: 'Art_187_Ley_19550'})
MATCH (b:Articulo {id: 'Art_167_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 167

// Art. 188
MATCH (a:Articulo {id: 'Art_188_Ley_19550'})
MATCH (b:Articulo {id: 'Art_202_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 202

// Art. 192
MATCH (a:Articulo {id: 'Art_192_Ley_19550'})
MATCH (b:Articulo {id: 'Art_37_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 37

// Art. 194
MATCH (a:Articulo {id: 'Art_194_Ley_19550'})
MATCH (b:Articulo {id: 'Art_197_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 197

MATCH (a:Articulo {id: 'Art_194_Ley_19550'})
MATCH (b:Articulo {id: 'Art_216_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 216

MATCH (a:Articulo {id: 'Art_194_Ley_19550'})
MATCH (b:Articulo {id: 'Art_250_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 250

MATCH (a:Articulo {id: 'Art_194_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

// Art. 195
MATCH (a:Articulo {id: 'Art_195_Ley_19550'})
MATCH (b:Articulo {id: 'Art_194_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 194

// Art. 197
MATCH (a:Articulo {id: 'Art_197_Ley_19550'})
MATCH (b:Articulo {id: 'Art_244_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 244

// Art. 19
MATCH (a:Articulo {id: 'Art_19_Ley_19550'})
MATCH (b:Articulo {id: 'Art_18_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 18

// Art. 202
MATCH (a:Articulo {id: 'Art_202_Ley_19550'})
MATCH (b:Articulo {id: 'Art_203_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 203 y 204

MATCH (a:Articulo {id: 'Art_202_Ley_19550'})
MATCH (b:Articulo {id: 'Art_204_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 203 y 204

// Art. 204
MATCH (a:Articulo {id: 'Art_204_Ley_19550'})
MATCH (b:Articulo {id: 'Art_83_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 83

// Art. 208
MATCH (a:Articulo {id: 'Art_208_Ley_19550'})
MATCH (b:Articulo {id: 'Art_211_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 211 y 212

MATCH (a:Articulo {id: 'Art_208_Ley_19550'})
MATCH (b:Articulo {id: 'Art_212_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 211 y 212

MATCH (a:Articulo {id: 'Art_208_Ley_19550'})
MATCH (b:Articulo {id: 'Art_213_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 213

// Art. 20
MATCH (a:Articulo {id: 'Art_20_Ley_19550'})
MATCH (b:Articulo {id: 'Art_18_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 18

// Art. 217
MATCH (a:Articulo {id: 'Art_217_Ley_19550'})
MATCH (b:Articulo {id: 'Art_244_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 244

// Art. 221
MATCH (a:Articulo {id: 'Art_221_Ley_19550'})
MATCH (b:Articulo {id: 'Art_194_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 194

// Art. 224
MATCH (a:Articulo {id: 'Art_224_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

// Art. 232
MATCH (a:Articulo {id: 'Art_232_Ley_19550'})
MATCH (b:Articulo {id: 'Art_228_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 228 y 230

MATCH (a:Articulo {id: 'Art_232_Ley_19550'})
MATCH (b:Articulo {id: 'Art_230_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 228 y 230

MATCH (a:Articulo {id: 'Art_232_Ley_19550'})
MATCH (b:Articulo {id: 'Art_237_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 237

// Art. 233
MATCH (a:Articulo {id: 'Art_233_Ley_19550'})
MATCH (b:Articulo {id: 'Art_234_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 234 y 235

MATCH (a:Articulo {id: 'Art_233_Ley_19550'})
MATCH (b:Articulo {id: 'Art_235_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 234 y 235

MATCH (a:Articulo {id: 'Art_233_Ley_19550'})
MATCH (b:Articulo {id: 'Art_245_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 245

// Art. 234
MATCH (a:Articulo {id: 'Art_234_Ley_19550'})
MATCH (b:Articulo {id: 'Art_188_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 188

// Art. 235
MATCH (a:Articulo {id: 'Art_235_Ley_19550'})
MATCH (b:Articulo {id: 'Art_188_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 188

MATCH (a:Articulo {id: 'Art_235_Ley_19550'})
MATCH (b:Articulo {id: 'Art_197_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 197;

// Art. 237
MATCH (a:Articulo {id: 'Art_237_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

// Art. 245
MATCH (a:Articulo {id: 'Art_245_Ley_19550'})
MATCH (b:Articulo {id: 'Art_244_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 244

MATCH (a:Articulo {id: 'Art_245_Ley_19550'})
MATCH (b:Articulo {id: 'Art_94_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 94

// Art. 247
MATCH (a:Articulo {id: 'Art_247_Ley_19550'})
MATCH (b:Articulo {id: 'Art_238_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 238

// Art. 249
MATCH (a:Articulo {id: 'Art_249_Ley_19550'})
MATCH (b:Articulo {id: 'Art_73_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 73

// Art. 24
MATCH (a:Articulo {id: 'Art_24_Ley_19550'})
MATCH (b:Articulo {id: 'Art_22_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 22;

// Art. 253
MATCH (a:Articulo {id: 'Art_253_Ley_19550'})
MATCH (b:Articulo {id: 'Art_250_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 250

MATCH (a:Articulo {id: 'Art_253_Ley_19550'})
MATCH (b:Articulo {id: 'Art_251_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 251

// Art. 255
MATCH (a:Articulo {id: 'Art_255_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

// Art. 256
MATCH (a:Articulo {id: 'Art_256_Ley_19550'})
MATCH (b:Articulo {id: 'Art_281_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 281

// Art. 257
MATCH (a:Articulo {id: 'Art_257_Ley_19550'})
MATCH (b:Articulo {id: 'Art_281_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 281

// Art. 25
MATCH (a:Articulo {id: 'Art_25_Ley_19550'})
MATCH (b:Articulo {id: 'Art_92_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 92

// Art. 262
MATCH (a:Articulo {id: 'Art_262_Ley_19550'})
MATCH (b:Articulo {id: 'Art_264_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 264 y 276

MATCH (a:Articulo {id: 'Art_262_Ley_19550'})
MATCH (b:Articulo {id: 'Art_276_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 264 y 276

// Art. 263
MATCH (a:Articulo {id: 'Art_263_Ley_19550'})
MATCH (b:Articulo {id: 'Art_262_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 262

// Art. 265
MATCH (a:Articulo {id: 'Art_265_Ley_19550'})
MATCH (b:Articulo {id: 'Art_264_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 264

// Art. 268
MATCH (a:Articulo {id: 'Art_268_Ley_19550'})
MATCH (b:Articulo {id: 'Art_58_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 58

// Art. 272
MATCH (a:Articulo {id: 'Art_272_Ley_19550'})
MATCH (b:Articulo {id: 'Art_59_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 59

// Art. 273
MATCH (a:Articulo {id: 'Art_273_Ley_19550'})
MATCH (b:Articulo {id: 'Art_59_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 59

// Art. 274
MATCH (a:Articulo {id: 'Art_274_Ley_19550'})
MATCH (b:Articulo {id: 'Art_59_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 59

// Art. 276
MATCH (a:Articulo {id: 'Art_276_Ley_19550'})
MATCH (b:Articulo {id: 'Art_275_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 275

// Art. 277
MATCH (a:Articulo {id: 'Art_277_Ley_19550'})
MATCH (b:Articulo {id: 'Art_276_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 276

// Art. 280
MATCH (a:Articulo {id: 'Art_280_Ley_19550'})
MATCH (b:Articulo {id: 'Art_234_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 234

MATCH (a:Articulo {id: 'Art_280_Ley_19550'})
MATCH (b:Articulo {id: 'Art_262_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 262

MATCH (a:Articulo {id: 'Art_280_Ley_19550'})
MATCH (b:Articulo {id: 'Art_263_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 262 y 263

MATCH (a:Articulo {id: 'Art_280_Ley_19550'})
MATCH (b:Articulo {id: 'Art_60_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 60

// Art. 281
MATCH (a:Articulo {id: 'Art_281_Ley_19550'})
MATCH (b:Articulo {id: 'Art_236_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 236

MATCH (a:Articulo {id: 'Art_281_Ley_19550'})
MATCH (b:Articulo {id: 'Art_58_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 58

// Art. 283
MATCH (a:Articulo {id: 'Art_283_Ley_19550'})
MATCH (b:Articulo {id: 'Art_284_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 284

// Art. 284
MATCH (a:Articulo {id: 'Art_284_Ley_19550'})
MATCH (b:Articulo {id: 'Art_288_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 288

MATCH (a:Articulo {id: 'Art_284_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

MATCH (a:Articulo {id: 'Art_284_Ley_19550'})
MATCH (b:Articulo {id: 'Art_55_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 55

// Art. 286
MATCH (a:Articulo {id: 'Art_286_Ley_19550'})
MATCH (b:Articulo {id: 'Art_264_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 264;

// Art. 288
MATCH (a:Articulo {id: 'Art_288_Ley_19550'})
MATCH (b:Articulo {id: 'Art_286_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 286 y 296

MATCH (a:Articulo {id: 'Art_288_Ley_19550'})
MATCH (b:Articulo {id: 'Art_296_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 286 y 296

// Art. 289
MATCH (a:Articulo {id: 'Art_289_Ley_19550'})
MATCH (b:Articulo {id: 'Art_263_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 263

// Art. 290
MATCH (a:Articulo {id: 'Art_290_Ley_19550'})
MATCH (b:Articulo {id: 'Art_294_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 294

// Art. 298
MATCH (a:Articulo {id: 'Art_298_Ley_19550'})
MATCH (b:Articulo {id: 'Art_271_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 271

// Art. 29
MATCH (a:Articulo {id: 'Art_29_Ley_19550'})
MATCH (b:Articulo {id: 'Art_28_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 28

// Art. 300
MATCH (a:Articulo {id: 'Art_300_Ley_19550'})
MATCH (b:Articulo {id: 'Art_167_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 53 y 167

MATCH (a:Articulo {id: 'Art_300_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

MATCH (a:Articulo {id: 'Art_300_Ley_19550'})
MATCH (b:Articulo {id: 'Art_53_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 53 y 167

// Art. 301
MATCH (a:Articulo {id: 'Art_301_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

// Art. 303
MATCH (a:Articulo {id: 'Art_303_Ley_19550'})
MATCH (b:Articulo {id: 'Art_301_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 301

MATCH (a:Articulo {id: 'Art_303_Ley_19550'})
MATCH (b:Articulo {id: 'Art_94_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 94

// Art. 305
MATCH (a:Articulo {id: 'Art_305_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

MATCH (a:Articulo {id: 'Art_305_Ley_19550'})
MATCH (b:Articulo {id: 'Art_302_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 302

// Art. 307
MATCH (a:Articulo {id: 'Art_307_Ley_19550'})
MATCH (b:Articulo {id: 'Art_169_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 169

// Art. 310
MATCH (a:Articulo {id: 'Art_310_Ley_19550'})
MATCH (b:Articulo {id: 'Art_264_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 264

MATCH (a:Articulo {id: 'Art_310_Ley_19550'})
MATCH (b:Articulo {id: 'Art_311_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 311

// Art. 311
MATCH (a:Articulo {id: 'Art_311_Ley_19550'})
MATCH (b:Articulo {id: 'Art_261_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 261

MATCH (a:Articulo {id: 'Art_311_Ley_19550'})
MATCH (b:Articulo {id: 'Art_263_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 263

// Art. 312
MATCH (a:Articulo {id: 'Art_312_Ley_19550'})
MATCH (b:Articulo {id: 'Art_308_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 308

// Art. 317
MATCH (a:Articulo {id: 'Art_317_Ley_19550'})
MATCH (b:Articulo {id: 'Art_126_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 126

// Art. 318
MATCH (a:Articulo {id: 'Art_318_Ley_19550'})
MATCH (b:Articulo {id: 'Art_257_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 257

// Art. 319
MATCH (a:Articulo {id: 'Art_319_Ley_19550'})
MATCH (b:Articulo {id: 'Art_129_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 129

// Art. 322
MATCH (a:Articulo {id: 'Art_322_Ley_19550'})
MATCH (b:Articulo {id: 'Art_319_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 319

// Art. 323
MATCH (a:Articulo {id: 'Art_323_Ley_19550'})
MATCH (b:Articulo {id: 'Art_244_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 244

// Art. 324
MATCH (a:Articulo {id: 'Art_324_Ley_19550'})
MATCH (b:Articulo {id: 'Art_315_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 315 y 316

MATCH (a:Articulo {id: 'Art_324_Ley_19550'})
MATCH (b:Articulo {id: 'Art_316_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 315 y 316

// Art. 32
MATCH (a:Articulo {id: 'Art_32_Ley_19550'})
MATCH (b:Articulo {id: 'Art_31_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 31

// Art. 339
MATCH (a:Articulo {id: 'Art_339_Ley_19550'})
MATCH (b:Articulo {id: 'Art_168_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 168

MATCH (a:Articulo {id: 'Art_339_Ley_19550'})
MATCH (b:Articulo {id: 'Art_172_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 172

// Art. 340
MATCH (a:Articulo {id: 'Art_340_Ley_19550'})
MATCH (b:Articulo {id: 'Art_336_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 336

// Art. 355
MATCH (a:Articulo {id: 'Art_355_Ley_19550'})
MATCH (b:Articulo {id: 'Art_251_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 251

// Art. 35
MATCH (a:Articulo {id: 'Art_35_Ley_19550'})
MATCH (b:Articulo {id: 'Art_125_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 125

// Art. 360
MATCH (a:Articulo {id: 'Art_360_Ley_19550'})
MATCH (b:Articulo {id: 'Art_7_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 7

// Art. 37
MATCH (a:Articulo {id: 'Art_37_Ley_19550'})
MATCH (b:Articulo {id: 'Art_193_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 193

// Art. 42
MATCH (a:Articulo {id: 'Art_42_Ley_19550'})
MATCH (b:Articulo {id: 'Art_51_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 51

// Art. 48
MATCH (a:Articulo {id: 'Art_48_Ley_19550'})
MATCH (b:Articulo {id: 'Art_46_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 46

// Art. 53
MATCH (a:Articulo {id: 'Art_53_Ley_19550'})
MATCH (b:Articulo {id: 'Art_169_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 169

// Art. 55
MATCH (a:Articulo {id: 'Art_55_Ley_19550'})
MATCH (b:Articulo {id: 'Art_158_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 158

MATCH (a:Articulo {id: 'Art_55_Ley_19550'})
MATCH (b:Articulo {id: 'Art_284_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 284

// Art. 5
MATCH (a:Articulo {id: 'Art_5_Ley_19550'})
MATCH (b:Articulo {id: 'Art_11_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 11

// Art. 60
MATCH (a:Articulo {id: 'Art_60_Ley_19550'})
MATCH (b:Articulo {id: 'Art_12_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 12

// Art. 61
MATCH (a:Articulo {id: 'Art_61_Ley_19550'})
MATCH (b:Articulo {id: 'Art_162_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 73, 162, 213, 238 y 290

MATCH (a:Articulo {id: 'Art_61_Ley_19550'})
MATCH (b:Articulo {id: 'Art_213_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 73, 162, 213, 238 y 290

MATCH (a:Articulo {id: 'Art_61_Ley_19550'})
MATCH (b:Articulo {id: 'Art_238_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 73, 162, 213, 238 y 290

MATCH (a:Articulo {id: 'Art_61_Ley_19550'})
MATCH (b:Articulo {id: 'Art_290_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 73, 162, 213, 238 y 290

MATCH (a:Articulo {id: 'Art_61_Ley_19550'})
MATCH (b:Articulo {id: 'Art_73_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 73, 162, 213, 238 y 290

// Art. 62
MATCH (a:Articulo {id: 'Art_62_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

MATCH (a:Articulo {id: 'Art_62_Ley_19550'})
MATCH (b:Articulo {id: 'Art_33_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 33

MATCH (a:Articulo {id: 'Art_62_Ley_19550'})
MATCH (b:Articulo {id: 'Art_63_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 63

MATCH (a:Articulo {id: 'Art_62_Ley_19550'})
MATCH (b:Articulo {id: 'Art_64_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 64

MATCH (a:Articulo {id: 'Art_62_Ley_19550'})
MATCH (b:Articulo {id: 'Art_65_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 65

MATCH (a:Articulo {id: 'Art_62_Ley_19550'})
MATCH (b:Articulo {id: 'Art_66_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 66

MATCH (a:Articulo {id: 'Art_62_Ley_19550'})
MATCH (b:Articulo {id: 'Art_67_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 67

// Art. 63
MATCH (a:Articulo {id: 'Art_63_Ley_19550'})
MATCH (b:Articulo {id: 'Art_220_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 220

// Art. 65
MATCH (a:Articulo {id: 'Art_65_Ley_19550'})
MATCH (b:Articulo {id: 'Art_220_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 220;
2

MATCH (a:Articulo {id: 'Art_65_Ley_19550'})
MATCH (b:Articulo {id: 'Art_271_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 271

MATCH (a:Articulo {id: 'Art_65_Ley_19550'})
MATCH (b:Articulo {id: 'Art_63_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 63 y 64

MATCH (a:Articulo {id: 'Art_65_Ley_19550'})
MATCH (b:Articulo {id: 'Art_64_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 63 y 64

// Art. 66
MATCH (a:Articulo {id: 'Art_66_Ley_19550'})
MATCH (b:Articulo {id: 'Art_64_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 64

// Art. 67
MATCH (a:Articulo {id: 'Art_67_Ley_19550'})
MATCH (b:Articulo {id: 'Art_299_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 299

// Art. 68
MATCH (a:Articulo {id: 'Art_68_Ley_19550'})
MATCH (b:Articulo {id: 'Art_224_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 224

MATCH (a:Articulo {id: 'Art_68_Ley_19550'})
MATCH (b:Articulo {id: 'Art_225_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 225

// Art. 70
MATCH (a:Articulo {id: 'Art_70_Ley_19550'})
MATCH (b:Articulo {id: 'Art_244_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 244

// Art. 77
MATCH (a:Articulo {id: 'Art_77_Ley_19550'})
MATCH (b:Articulo {id: 'Art_10_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 10

// Art. 80
MATCH (a:Articulo {id: 'Art_80_Ley_19550'})
MATCH (b:Articulo {id: 'Art_81_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 81

// Art. 83
MATCH (a:Articulo {id: 'Art_83_Ley_19550'})
MATCH (b:Articulo {id: 'Art_98_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 98

// Art. 84
MATCH (a:Articulo {id: 'Art_84_Ley_19550'})
MATCH (b:Articulo {id: 'Art_87_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 87

// Art. 85
MATCH (a:Articulo {id: 'Art_85_Ley_19550'})
MATCH (b:Articulo {id: 'Art_78_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 78 y 79

MATCH (a:Articulo {id: 'Art_85_Ley_19550'})
MATCH (b:Articulo {id: 'Art_79_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 78 y 79

// Art. 88
MATCH (a:Articulo {id: 'Art_88_Ley_19550'})
MATCH (b:Articulo {id: 'Art_78_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 78 y 79

MATCH (a:Articulo {id: 'Art_88_Ley_19550'})
MATCH (b:Articulo {id: 'Art_79_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 78 y 79

MATCH (a:Articulo {id: 'Art_88_Ley_19550'})
MATCH (b:Articulo {id: 'Art_83_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículos 83

MATCH (a:Articulo {id: 'Art_88_Ley_19550'})
MATCH (b:Articulo {id: 'Art_84_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 84

// Art. 92
MATCH (a:Articulo {id: 'Art_92_Ley_19550'})
MATCH (b:Articulo {id: 'Art_49_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 49

// Art. 93
MATCH (a:Articulo {id: 'Art_93_Ley_19550'})
MATCH (b:Articulo {id: 'Art_92_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 92

MATCH (a:Articulo {id: 'Art_93_Ley_19550'})
MATCH (b:Articulo {id: 'Art_94_bis_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 94 bis

// Art. 94
MATCH (a:Articulo {id: 'Art_94_Ley_19550'})
MATCH (b:Articulo {id: 'Art_244_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 244

MATCH (a:Articulo {id: 'Art_94_Ley_19550'})
MATCH (b:Articulo {id: 'Art_82_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 82;


// Art. 95
MATCH (a:Articulo {id: 'Art_95_Ley_19550'})
MATCH (b:Articulo {id: 'Art_99_Ley_19550'})
MERGE (a)-[:REMITE_A]->(b);  // artículo 99

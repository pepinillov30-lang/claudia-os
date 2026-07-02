import { Telegraf } from 'telegraf';
import { createServer } from 'http';
import { existsSync, mkdirSync, appendFileSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';
import {
  BOT_TOKEN, ALLOWED_USER_ID, PROJECTS, DEFAULT_PROJECT,
  TMP_DIR, CALENDAR_SCRIPT, HTTP_PORT, HTTP_SECRET,
  CLAUDIA_ROOT,
} from './config.js';
import { runClaude, injectSessionContext } from './claude.js';
import { enqueue, cancelCurrent, getQueueLength, isBusy } from './queue.js';
import { loadSessions, getSession, setSession, clearSession } from './session.js';
import { transcribeAudio, isWhisperAvailable } from './transcriber.js';
import { splitMessage, downloadFile, cleanupFile } from './utils.js';

// Init
loadSessions();

if (!existsSync(TMP_DIR)) mkdirSync(TMP_DIR, { recursive: true });

const bot = new Telegraf(BOT_TOKEN, { handlerTimeout: 10 * 60 * 1000 });

// Auth: solo el usuario autorizado. El resto se ignora.
bot.use((ctx, next) => {
  if (ctx.from?.id !== ALLOWED_USER_ID) return;
  return next();
});

// --- Comandos ---

bot.command('start', (ctx) => ctx.reply(helpText()));
bot.command('help', (ctx) => ctx.reply(helpText()));

bot.command('facturas', async (ctx) => {
  const prompt =
    'Ejecuta la skill /claudia-holded en modo "procesar": escanea las facturas de proveedor ' +
    'etiquetadas y SIN procesar (inbox.py pending) en las cuentas configuradas. Para cada una: ' +
    'descarga el PDF (inbox.py download), extrae los datos (emisor FISCAL real, NIF, nº, fecha, ' +
    'base, IVA, total, escenario) y pásalos a ingest.py --json (valida, deduplica y crea el ' +
    'borrador con PDF adjunto). Según el status: created/duplicate → marca el correo procesado ' +
    '(inbox.py mark); error (proveedor no encontrado / datos incompletos / sin contabilización) → ' +
    'NO marques, y al terminar PREGÚNTAME aquí en el chat lo que falte. Responde con un resumen: ' +
    'nuevas creadas, ya existentes y lo que necesita mi decisión.';
  await handlePrompt(ctx, prompt);
});

bot.command('new', (ctx) => {
  clearSession(ctx.chat.id);
  ctx.reply('Nueva sesión. Contexto limpio.');
});

bot.command('project', (ctx) => {
  const name = ctx.message.text.split(/\s+/)[1]?.toLowerCase();
  if (!name || !PROJECTS[name]) {
    const available = Object.keys(PROJECTS).join(', ');
    return ctx.reply(`Proyecto no válido. Disponibles: ${available}`);
  }
  setSession(ctx.chat.id, { project: name, sessionId: null });
  ctx.reply(`Proyecto: ${name}\nSesión reiniciada.`);
});

bot.command('status', (ctx) => {
  const session = getSession(ctx.chat.id);
  const project = session?.project || DEFAULT_PROJECT;
  const hasSession = session?.sessionId ? 'Sí' : 'No';

  ctx.reply(
    `Proyecto: ${project}\n` +
    `Sesión activa: ${hasSession}\n` +
    `Procesando: ${isBusy() ? 'Sí' : 'No'}\n` +
    `Cola: ${getQueueLength()} pendientes\n` +
    `Whisper: ${isWhisperAvailable() ? 'OK' : 'No disponible'}`
  );
});

bot.command('cancel', (ctx) => {
  if (cancelCurrent()) {
    ctx.reply('Tarea cancelada.');
  } else {
    ctx.reply('No hay tarea en ejecución.');
  }
});

// /agenda [días] — consulta directa al calendario sin pasar por Claude
bot.command('agenda', async (ctx) => {
  const days = parseInt(ctx.message.text.split(/\s+/)[1]) || 1;
  try {
    const result = execSync(`python3 "${CALENDAR_SCRIPT}" --days ${Math.min(days, 30)}`, {
      timeout: 15000,
      encoding: 'utf8',
    });
    const chunks = splitMessage(result || 'No hay eventos.');
    for (const chunk of chunks) {
      await ctx.reply(chunk);
    }
  } catch (err) {
    ctx.reply(`Error al consultar el calendario: ${err.message.slice(0, 300)}`);
  }
});

// --- Intake: paths ---

const INTAKE_ADD_SCRIPT = join(
  CLAUDIA_ROOT,
  '.claude/skills/claudia-intake/intake_add.py'
);

// --- Mensajes de texto ---

bot.on('text', async (ctx) => {
  const text = ctx.message.text;
  if (text.startsWith('/')) return;

  // Intake: comando "procesa N,M" (respuesta a briefing de feeds)
  const processMatch = text.trim().match(/^procesa\s+([\d,\s]+)$/i);
  if (processMatch) {
    try {
      const indices = processMatch[1].split(',').map(s => s.trim()).filter(Boolean).join(',');
      const result = execSync(
        `python3 "${INTAKE_ADD_SCRIPT}" --promote-feed ${indices}`,
        { timeout: 10000, encoding: 'utf8' }
      );
      const parsed = JSON.parse(result);
      if (parsed.promoted > 0) {
        await ctx.reply(`Encolados: ${parsed.titles.join(', ')}. Se procesarán en el próximo ciclo.`);
      } else {
        await ctx.reply('No se encontraron items de feeds con esos índices.');
      }
    } catch (err) {
      await ctx.reply(`Error al procesar feeds: ${err.message.slice(0, 200)}`);
    }
    return;
  }

  // OAuth: detect localhost redirect URLs with code parameter (Google Health token renewal)
  const oauthCodeMatch = text.match(/https?:\/\/localhost\S*[?&]code=([^&\s]+)/);
  if (oauthCodeMatch) {
    try {
      const code = oauthCodeMatch[1];
      const HEALTH_VENV = join(CLAUDIA_ROOT, '.claude/skills/claudia-health/venv/bin/python3');
      const AUTH_SCRIPT = join(CLAUDIA_ROOT, '.claude/skills/claudia-health/auth_telegram.py');
      const result = execSync(
        `"${HEALTH_VENV}" "${AUTH_SCRIPT}" --exchange-code "${code}" --account sergi`,
        { timeout: 15000, encoding: 'utf8' }
      );
      const parsed = JSON.parse(result);
      if (parsed.status === 'success') {
        await ctx.reply(`✅ ${parsed.message}. El sync se reanudará automáticamente.`);
      } else {
        await ctx.reply(`❌ ${parsed.error}`);
      }
    } catch (err) {
      await ctx.reply(`Error procesando OAuth: ${err.message.slice(0, 300)}`);
    }
    return;
  }

  // Intake: URL bare o con keyword "intake"/"encola"
  const urlMatch = text.match(/https?:\/\/[^\s]+/);
  const isIntakeKeyword = /\b(intake|encola|guarda esto)\b/i.test(text);
  const isBareUrl = urlMatch && text.trim() === urlMatch[0];

  if (urlMatch && (isBareUrl || isIntakeKeyword)) {
    try {
      const url = urlMatch[0];
      const context = text !== url ? text.replace(url, '').trim() : '';
      const args = [`--url`, url, `--source`, `telegram`];
      if (context) args.push(`--context`, context);
      const result = execSync(
        `python3 "${INTAKE_ADD_SCRIPT}" ${args.map(a => `"${a}"`).join(' ')}`,
        { timeout: 10000, encoding: 'utf8' }
      );
      const parsed = JSON.parse(result);
      if (parsed.status === 'duplicate') {
        await ctx.reply('Ya está en la cola.');
      } else {
        await ctx.reply('Encolado para el próximo briefing.');
      }
    } catch (err) {
      await ctx.reply(`Error al encolar: ${err.message.slice(0, 200)}`);
    }
    return;
  }

  await handlePrompt(ctx, text);
});

// --- Audio ---

bot.on('voice', async (ctx) => {
  if (!isWhisperAvailable()) {
    return ctx.reply('Whisper no está disponible. Escríbelo.');
  }

  const waiting = await ctx.reply('Transcribiendo audio...');

  try {
    const fileId = ctx.message.voice.file_id;
    const oggPath = join(TMP_DIR, `voice_${Date.now()}.ogg`);
    await downloadFile(bot, fileId, oggPath);

    const transcription = await transcribeAudio(oggPath);
    await ctx.telegram.editMessageText(
      ctx.chat.id, waiting.message_id, null,
      `Transcripción: ${transcription}\n\nProcesando...`
    );

    await handlePrompt(ctx, transcription);
  } catch (err) {
    console.error('[VOICE ERR]', err.message);
    await ctx.telegram.editMessageText(
      ctx.chat.id, waiting.message_id, null,
      `No pude transcribir el audio: ${err.message}`
    );
  }
});

// --- Fotos ---

const TICKET_KEYWORDS = /\b(ticket|recibo|tiquet|mercadona|lidl|bonpreu|aldi|consum|carrefour|dia|eroski|alcampo|hipercor|supermercado|super)\b/i;

bot.on('photo', async (ctx) => {
  const photo = ctx.message.photo[ctx.message.photo.length - 1];
  const caption = ctx.message.caption || '';
  const imgPath = join(TMP_DIR, `img_${Date.now()}.jpg`);

  const isTicket = TICKET_KEYWORDS.test(caption);
  const waiting = await ctx.reply(isTicket ? 'Procesando ticket...' : 'Procesando imagen...');

  try {
    await downloadFile(bot, photo.file_id, imgPath);

    let prompt;
    if (isTicket) {
      prompt = `Lee la imagen del ticket de compra en ${imgPath}. Ejecuta el flujo /claudia-finanzas enrich: extrae cada producto con su precio, genera el CSV de enrichment en data/enrichments/ticket_{año}.csv (append), ejecuta enrich_products.py, match_enrichments.py, categorize.py --recat y generate.py. Workspace: user/workspaces/finanzas. Responde con un resumen de los productos extraídos y su categorización.`;
    } else {
      prompt = `Lee la imagen en ${imgPath} y responde: ${caption || 'Describe esta imagen'}`;
    }

    await handlePrompt(ctx, prompt);
  } catch (err) {
    console.error('[PHOTO ERR]', err.message);
    await ctx.telegram.editMessageText(
      ctx.chat.id, waiting.message_id, null,
      `Error con la imagen: ${err.message}`
    );
  } finally {
    cleanupFile(imgPath);
  }
});

// --- Documentos (facturas PDF → Holded) ---

const INVOICE_INBOX = join(CLAUDIA_ROOT, 'user', 'workspaces', 'facturacion', 'inbox');

bot.on('document', async (ctx) => {
  const doc = ctx.message.document;
  const caption = ctx.message.caption || '';
  const name = doc.file_name || `factura_${Date.now()}.pdf`;
  const isPdf = doc.mime_type === 'application/pdf' || /\.pdf$/i.test(name);

  if (!isPdf) {
    await ctx.reply('Por ahora solo proceso facturas en PDF.');
    return;
  }

  if (!existsSync(INVOICE_INBOX)) mkdirSync(INVOICE_INBOX, { recursive: true });
  const safe = name.replace(/[^\w.\-]/g, '_');
  const pdfPath = join(INVOICE_INBOX, `${Date.now()}__${safe}`);
  const waiting = await ctx.reply('Factura recibida. Procesando y subiendo a Holded...');

  try {
    await downloadFile(bot, doc.file_id, pdfPath);
    const prompt =
      `El usuario ha enviado un DOCUMENTO PDF por Telegram, guardado en ${pdfPath}.\n` +
      `PASO 0 — CLASIFICA el documento leyendo el PDF, y enruta:\n` +
      `- FACTURA DE COMPRA de un proveedor → procédela con /claudia-holded (pasos abajo).\n` +
      `- EXTRACTO BANCARIO o TICKET de compra → es de /claudia-finanzas, NO de Holded: dilo y no subas nada a Holded (procesa en finanzas solo si el usuario lo pide).\n` +
      `- Otro tipo, o dudas de qué es → NO subas nada; pregunta al usuario qué quiere hacer.\n` +
      `Solo si es una factura de compra de proveedor, sigue con /claudia-holded (modo ingest de PDF suelto):\n` +
      `1) Extrae del PDF: emisor (razón social FISCAL real — ojo marca vs emisor), NIF/CIF, nº factura, fecha (YYYY-MM-DD), base, tipo y cuota de IVA, total, escenario de IVA (nacional/intracom/reverse_charge/...).\n` +
      `2) Escribe esos campos a un JSON (supplier_name, nif, number, date, base, total, iva_rate, tax_scenario, y pdf="${pdfPath}") y pásalo a ingest.py:\n` +
      `   python3 .claude/skills/claudia-holded/ingest.py --json <fichero.json>\n` +
      `   ingest.py VALIDA, deduplica y crea el BORRADOR con el PDF adjunto de forma determinista. NO construyas tú la llamada a la API ni uses holded.py create a mano.\n` +
      `3) Reporta según el "status" que devuelva ingest.py:\n` +
      `   - created → di proveedor, nº, total, "borrador creado".\n` +
      `   - duplicate → di que ya existía, no dupliques.\n` +
      `   - error (PROVEEDOR_NO_ENCONTRADO / DATOS_INCOMPLETOS / SIN_CONTABILIZACION) → explícaselo al usuario y pregunta lo que falte (contacto, cuenta, IVA...). NO subas nada.\n` +
      `Responde en 3-5 líneas: tipo de documento, proveedor, nº, total y resultado.` +
      (caption ? `\nNota del usuario (tenla en cuenta para clasificar y decidir): ${caption}` : '');
    await handlePrompt(ctx, prompt);
  } catch (err) {
    console.error('[DOC ERR]', err.message);
    await ctx.telegram.editMessageText(
      ctx.chat.id, waiting.message_id, null,
      `Error con la factura: ${err.message}`
    );
  }
});

// --- Handler principal ---

async function handlePrompt(ctx, prompt) {
  const chatId = ctx.chat.id;

  if (isBusy()) {
    const pos = getQueueLength() + 1;
    await ctx.reply(`En cola (posición ${pos}). Espera...`);
  }

  try {
    const result = await enqueue(async () => {
      const typing = setInterval(() => {
        ctx.sendChatAction('typing').catch(() => {});
      }, 4000);

      try {
        ctx.sendChatAction('typing').catch(() => {});
        return await runClaude(chatId, prompt);
      } finally {
        clearInterval(typing);
      }
    });

    const chunks = splitMessage(result);
    for (const chunk of chunks) {
      await ctx.reply(chunk, { parse_mode: undefined });
    }

    logInteraction(ctx, prompt, result);
  } catch (err) {
    console.error(`[CLAUDE ERR] ${err.message}`);
    await ctx.reply(`Error: ${err.message.slice(0, 500)}`);
    logInteraction(ctx, prompt, `ERROR: ${err.message}`);
  }
}

// --- Logging ---

function logInteraction(ctx, prompt, response) {
  try {
    const session = getSession(ctx.chat.id);
    const project = session?.project || DEFAULT_PROJECT;
    const logDir = join(PROJECTS[project] || PROJECTS.claudia, 'logs');

    if (!existsSync(logDir)) mkdirSync(logDir, { recursive: true });

    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10);
    const timeStr = now.toISOString();
    const logFile = join(logDir, `${dateStr}.md`);

    const entry = `\n### ${timeStr} — Telegram\n- **Prompt:** ${prompt.slice(0, 200)}\n- **Respuesta:** ${response.slice(0, 300)}\n`;
    appendFileSync(logFile, entry);
  } catch {
    // Logging no debería romper el flujo
  }
}

function helpText() {
  return (
    'Claudia OS — Bot de Telegram\n\n' +
    'Envía texto, audio o imagen y Claudia responde.\n\n' +
    'Comandos:\n' +
    '/agenda [días] — Consultar calendario (sin IA)\n' +
    '/new — Nueva sesión (olvida contexto)\n' +
    '/project <nombre> — Cambiar workspace\n' +
    '/status — Estado del bot\n' +
    '/facturas — Procesar facturas de proveedor pendientes (Holded)\n' +
    'Enviar un PDF — subir esa factura a Holded\n' +
    '/cancel — Cancelar tarea en ejecución\n' +
    '/help — Esta ayuda\n\n' +
    `Workspaces: ${Object.keys(PROJECTS).join(', ')}`
  );
}

// --- HTTP API (Siri / Tailscale) ---

createServer((req, res) => {
  if (req.method !== 'POST') {
    res.writeHead(404).end();
    return;
  }

  let body = '';
  req.on('data', chunk => { body += chunk; });
  req.on('end', async () => {
    try {
      const parsed = JSON.parse(body);

      if (req.url === '/inject-context') {
        const { text, secret } = parsed;
        if (!text || (HTTP_SECRET && secret !== HTTP_SECRET)) {
          res.writeHead(401).end('Unauthorized');
          return;
        }
        enqueue(async () => injectSessionContext(ALLOWED_USER_ID, text))
          .catch(err => console.error('[inject] Error en cola:', err.message));
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true }));
        return;
      }

      if (req.url === '/message') {
        const { text, secret, return_only } = parsed;

        if (!text || !HTTP_SECRET || secret !== HTTP_SECRET) {
          res.writeHead(401).end('Unauthorized');
          return;
        }
        const voice = /[,.]?\s*responde por voz\.?$/i.test(text);
        const cleanText = text.replace(/[,.]?\s*responde por voz\.?$/i, '').trim();

        if (return_only) {
          const result = await enqueue(async () => runClaude(ALLOWED_USER_ID, cleanText));
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ ok: true, result }));
          return;
        }

        let fullResponse = '';
        const fakeCtx = {
          chat: { id: ALLOWED_USER_ID },
          reply: (msg, opts) => {
            fullResponse += (fullResponse ? ' ' : '') + msg;
            return bot.telegram.sendMessage(ALLOWED_USER_ID, msg, opts);
          },
          sendChatAction: (action) => bot.telegram.sendChatAction(ALLOWED_USER_ID, action).catch(() => {}),
        };

        await handlePrompt(fakeCtx, cleanText);

        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ ok: true, voice_text: voice ? fullResponse : '' }));
        return;
      }

      res.writeHead(404).end();
    } catch {
      res.writeHead(400).end('Bad request');
    }
  });
}).listen(HTTP_PORT, '0.0.0.0', () => {
  console.log(`Claudia HTTP API escuchando en :${HTTP_PORT}`);
});

// --- Recuperación ante fallos de polling ---

bot.catch((err) => {
  console.error(`[BOT ERROR] ${err.message}`);
  const fatal = err.message?.includes('terminated by other getUpdates') ||
                err.code === 'EAI_AGAIN' ||
                err.code === 'ETIMEDOUT';
  if (fatal) {
    console.error('[BOT FATAL] Polling irrecuperable, saliendo para que PM2 reinicie...');
    process.exit(1);
  }
});

// --- Arranque ---

bot.launch({ dropPendingUpdates: false }).catch((err) => {
  // Fallo al ARRANCAR el polling (ej. EAI_AGAIN tras un reinicio del server,
  // cuando PM2 levanta el bot antes de que el DNS esté listo). Salimos para
  // que PM2 reintente (restart_delay) hasta que la red esté disponible.
  console.error(`[BOT LAUNCH FAIL] ${err.code || err.message} — saliendo para que PM2 reintente`);
  process.exit(1);
});
console.log('Claudia OS — Bot de Telegram iniciado');

process.once('SIGINT', () => bot.stop('SIGINT'));
process.once('SIGTERM', () => bot.stop('SIGTERM'));

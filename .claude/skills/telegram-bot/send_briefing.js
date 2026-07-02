#!/usr/bin/env node
/**
 * send_briefing.js
 * Lee briefing.json, genera el mensaje del briefing y lo envía por Telegram.
 *
 * Uso: node send_briefing.js <schedule_name>
 * Ejemplo: node send_briefing.js mañana
 */

import { readFileSync, existsSync } from 'fs';
import { join } from 'path';
import { execSync } from 'child_process';
import http from 'http';
import https from 'https';
import { CLAUDIA_ROOT } from './src/env.js';

const SETTINGS_FILE = join(CLAUDIA_ROOT, 'user/config/settings.json');

if (!existsSync(SETTINGS_FILE)) {
  console.log('[briefing] No existe settings.json, nada que hacer.');
  process.exit(0);
}

const settings = JSON.parse(readFileSync(SETTINGS_FILE, 'utf8'));
const config = settings.skill_briefing;

if (!config) {
  console.log('[briefing] No hay skill_briefing en settings.json, nada que hacer.');
  process.exit(0);
}

const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const CHAT_ID = process.env.TELEGRAM_USER_ID;

if (!BOT_TOKEN || !CHAT_ID) {
  console.error('[briefing] Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_USER_ID');
  process.exit(1);
}

if (!config.enabled) {
  console.log('[briefing] Briefing desactivado.');
  process.exit(0);
}

const scheduleName = process.argv[2];
if (!scheduleName) {
  console.error('[briefing] Uso: node send_briefing.js <schedule_name>');
  process.exit(1);
}

const schedule = config.schedules?.find(s => s.name === scheduleName);
if (!schedule) {
  console.error(`[briefing] Schedule "${scheduleName}" no encontrado en settings.json`);
  process.exit(1);
}

const tz = settings.timezone || 'UTC';
const now = new Date();

// Utilidades de fecha en la timezone configurada.
function todayIsoInTz(date, timeZone) {
  // 'en-CA' produce formato 'YYYY-MM-DD', estable y ordenable.
  return date.toLocaleDateString('en-CA', { timeZone });
}

function dayCodeInTz(date, timeZone) {
  const short = date.toLocaleDateString('en-US', { timeZone, weekday: 'short' }).toLowerCase();
  return short.slice(0, 3); // 'mon', 'tue', ...
}

// Verificar que hoy es un día válido para este schedule (en la TZ del usuario).
const today = dayCodeInTz(now, tz);
if (schedule.days && !schedule.days.includes(today)) {
  console.log(`[briefing] Hoy (${today}) no está en los días del schedule "${scheduleName}".`);
  process.exit(0);
}

// Generar las secciones
const parts = [];
const dateStr = now.toLocaleDateString('es-ES', {
  weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: tz
});

parts.push(`Buenos días. Hoy es ${dateStr}.`);

for (const sectionName of (schedule.sections || [])) {
  const sectionConfig = config.sections?.[sectionName];
  if (!sectionConfig) continue;

  if (sectionName === 'calendar') {
    const calendarText = buildCalendarSection(sectionConfig);
    if (calendarText) parts.push(calendarText);
  } else if (sectionName === 'health') {
    const healthText = buildHealthSection(sectionConfig);
    if (healthText) parts.push(healthText);
  } else if (sectionName === 'tasks') {
    const tasksText = buildTasksSection(sectionConfig);
    if (tasksText) parts.push(tasksText);
  }
}

const message = parts.join('\n\n');
await sendTelegram(message);
injectContext(message);
console.log(`[briefing] Enviado schedule "${scheduleName}".`);

// --- Section builders ---

function buildCalendarSection(cfg) {
  const daysAhead = cfg.days_ahead || 1;
  const calendarScript = join(CLAUDIA_ROOT, '.claude/skills/claudia-calendar/fetch_calendar.py');

  if (!existsSync(calendarScript)) {
    return '📅 Calendario: no disponible (fetch_calendar.py no encontrado).';
  }

  try {
    const output = execSync(`python3 "${calendarScript}" --days ${daysAhead}`, {
      timeout: 30000,
      encoding: 'utf8',
      env: { ...process.env, TZ: tz }
    }).trim();

    if (!output || output.startsWith('Error')) {
      return '📅 Calendario: no he podido consultar el calendario.';
    }
    return `📅 Agenda:\n${output}`;
  } catch (e) {
    console.error('[briefing] Error consultando calendario:', e.message);
    return '📅 Calendario: error al consultar.';
  }
}

function buildHealthSection(cfg) {
  const healthDb = join(CLAUDIA_ROOT, 'user/data/health/health.db');
  if (!existsSync(healthDb)) return null;

  try {
    // Sync sleep before querying (Fitbit data may arrive after briefing cron)
    const syncVenv = join(CLAUDIA_ROOT, '.claude/skills/claudia-health/venv/bin/python3');
    const syncScript = join(CLAUDIA_ROOT, '.claude/skills/claudia-health/sync.py');
    try {
      execSync(
        `${syncVenv} "${syncScript}" --account sergi --metrics sleep`,
        { timeout: 30000, encoding: 'utf8', env: { ...process.env } }
      );
    } catch (e) {
      console.error('[briefing] Pre-sync sleep failed:', e.message);
    }

    const yesterday = todayIsoInTz(new Date(now - 86400000), tz);
    const pyScript = join(CLAUDIA_ROOT, '.claude/skills/telegram-bot/src/health_briefing.py');

    const raw = execSync(
      `python3 "${pyScript}" "${healthDb}" "${yesterday}"`,
      { timeout: 10000, encoding: 'utf8' }
    ).trim();

    const data = JSON.parse(raw);
    if (!data.sleep && Object.keys(data.metrics).length === 0) {
      return '\u{1f4a4} Salud: sin datos de ayer.';
    }

    const lines = [];
    const sl = data.sleep;
    const sa = data.sleep_avg;

    if (sl) {
      const h = Math.floor(sl.duration_minutes / 60);
      const m = sl.duration_minutes % 60;
      const durStr = h + 'h' + (m > 0 ? m + 'min' : '');
      let sleepLine = '\u{1f4a4} Sueño: ' + durStr + ' (' + sl.efficiency + '% eficiencia)';
      if (sa && sa.avg_dur) {
        const avgH = Math.floor(sa.avg_dur / 60);
        const avgM = Math.round(sa.avg_dur % 60);
        sleepLine += ' — media 4sem: ' + avgH + 'h' + (avgM > 0 ? avgM + 'min' : '');
      }
      lines.push(sleepLine);

      const fmtStage = (label, mins, avgMins) => {
        let s = mins >= 60 ? label + ' ' + Math.floor(mins/60) + 'h' + (mins%60 > 0 ? (mins%60) + 'min' : '') : label + ' ' + mins + 'min';
        if (avgMins && avgMins > 0) {
          const diff = mins - avgMins;
          if (Math.abs(diff) >= 5) s += ' (' + (diff > 0 ? '+' : '') + Math.round(diff) + ')';
        }
        return s;
      };
      const stages = [];
      stages.push(fmtStage('Deep', sl.deep_minutes, sa?.avg_deep));
      stages.push(fmtStage('REM', sl.rem_minutes, sa?.avg_rem));
      stages.push(fmtStage('Light', sl.light_minutes, sa?.avg_light));
      if (sl.awake_minutes > 0) stages.push('Awake ' + sl.awake_minutes + 'min');
      lines.push('   ' + stages.join(' · '));
    }

    const metrics = data.metrics;
    const avgs = data.averages;
    const hrv = metrics['hrv_rmssd'];
    const rhr = metrics['resting_hr_daily'] || metrics['resting_hr'];
    const spo2 = metrics['spo2'];
    const steps = metrics['steps'];

    const vitals = [];
    if (hrv) {
      let v = 'HRV ' + Math.round(hrv.value) + 'ms';
      const a = avgs['hrv_rmssd'];
      if (a) v += ' (media ' + Math.round(a) + ')';
      vitals.push(v);
    }
    if (rhr) {
      let v = 'FC rep ' + Math.round(rhr.value) + 'bpm';
      const a = avgs['resting_hr_daily'] || avgs['resting_hr'];
      if (a) v += ' (media ' + Math.round(a) + ')';
      vitals.push(v);
    }
    if (spo2) vitals.push('SpO2 ' + Math.round(spo2.value) + '%');
    if (vitals.length > 0) lines.push('❤️ ' + vitals.join(' · '));

    if (steps) {
      let stepsLine = '\u{1f6b6} Ayer: ' + Math.round(steps.value).toLocaleString() + ' pasos';
      const avgSteps = avgs['steps'];
      if (avgSteps) stepsLine += ' (media 4sem: ' + Math.round(avgSteps).toLocaleString() + ')';
      lines.push(stepsLine);
    }

    if (cfg.show_recovery_hint && (hrv || rhr)) {
      let hint = '';
      if (hrv && hrv.value < 25) hint = '⚠️ HRV baja — prioriza descanso hoy';
      else if (hrv && hrv.value < 40) hint = '\u{1f49b} Recuperación moderada — entreno suave ok';
      else if (hrv) hint = '\u{1f49a} Buena recuperación — día para entrenar';
      if (hint) lines.push(hint);
    }

    return lines.length > 0 ? lines.join('\n') : null;
  } catch (e) {
    console.error('[briefing] Error consultando salud:', e.message);
    return '\u{1f4a4} Salud: error al consultar datos.';
  }
}

function buildTasksSection(cfg) {
  const tasksFile = join(CLAUDIA_ROOT, cfg.source || 'user/workspaces/_me/notes/tasks.md');
  if (!existsSync(tasksFile)) return null;

  const content = readFileSync(tasksFile, 'utf8');
  const lines = content.split('\n');
  const parts = [];

  if (cfg.show_due_today) {
    const todayStr = todayIsoInTz(now, tz);
    const dueToday = lines.filter(l =>
      l.match(/^- \[ \]/) && l.includes(todayStr)
    ).map(l => l.replace(/^- \[ \] \d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?(?:\s+\[ctx=\w+\])? — /, '• '));

    if (dueToday.length > 0) {
      parts.push(`⏰ Vence hoy:\n${dueToday.join('\n')}`);
    }
  }

  if (cfg.show_pending) {
    const pending = lines.filter(l => l.match(/^- \[ \]/) && !l.match(/\d{4}-\d{2}-\d{2}/));
    if (pending.length > 0) {
      const items = pending.map(l => l.replace(/^- \[ \] /, '• ')).slice(0, 10);
      parts.push(`📋 Pendiente:\n${items.join('\n')}`);
    }
  }

  return parts.length > 0 ? parts.join('\n\n') : null;
}

// --- Inyección de contexto en sesión de Claude ---

function injectContext(text) {
  const port = process.env.HTTP_PORT || 3001;
  const secret = process.env.HTTP_SECRET || '';

  const payload = JSON.stringify({ text, secret });
  const req = http.request({
    hostname: 'localhost',
    port,
    path: '/inject-context',
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(payload) },
  }, (res) => { res.resume(); });
  req.on('error', (e) => console.error('[briefing] Error inyectando contexto:', e.message));
  req.write(payload);
  req.end();
}

// --- Telegram ---

function sendTelegram(text) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ chat_id: CHAT_ID, text });
    const req = https.request({
      hostname: 'api.telegram.org',
      path: `/bot${BOT_TOKEN}/sendMessage`,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, (res) => {
      res.resume();
      resolve();
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

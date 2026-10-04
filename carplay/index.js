// Процесс CarPlay: держит донгл, показывает картинку, играет звук.
//
// Решений он не принимает. Какую кнопку куда, показывать или прятать —
// это дело автомата на питоне, который покрыт тестами. Здесь только
// исполнение: получить кадр и отдать его дальше.
//
// Протокол на сокете — строки JSON, по одной на строку:
//
//   нам     {"cmd":"navigate","right":true,"steps":1}
//           {"cmd":"select"}  {"cmd":"back"}  {"cmd":"home"}
//   от нас  {"event":"phone","connected":true}
//
// Запуск:
//   node index.js                     как есть
//   node index.js --bez-videa         только сокет, без окна: отладка логики
//   node index.js --zvuk carplay      ALSA PCM с микшером plug/dmix

import { spawn } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import process from 'node:process'
import { Readable, Writable } from 'node:stream'

import CarplayNode from 'node-carplay/node'
import { DongleDriver, DEFAULT_CONFIG, SendCommand, SendTouch, TouchAction, decodeTypeMap, AudioCommand } from 'node-carplay/node'
import { usb, webusb } from 'usb'

const SOCKET = process.env.CARPLAY_SOCKET || '/tmp/carplay.sock'

function arg(name, fallback) {
  const i = process.argv.indexOf(name)
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}
const flag = (name) => process.argv.includes(name)

const WIDTH = Number(arg('--shirina', 800))
const HEIGHT = Number(arg('--vysota', 480))
const FPS = Number(arg('--fps', 20))
if (![WIDTH, HEIGHT].every((v) => Number.isInteger(v) && v >= 2 && v <= 4096) ||
    !Number.isInteger(FPS) || FPS < 1 || FPS > 120) throw new Error('неверные размеры видео или fps')
// Через dmix, а не напрямую: параллельно с нами тишину гоняет служба
// zvuk-zhivoy, иначе кодек засыпает и радио теряет вход AUX.
const AUDIO_DEVICE = arg('--zvuk', 'carplay')
if (/^(?:plug)?hw(?::|$)/.test(AUDIO_DEVICE)) {
  throw new Error('--zvuk требует ALSA-микшер (например carplay), а не эксклюзивный hw:')
}
const NO_VIDEO = flag('--bez-videa')
const NIGHT = flag('--noch')
// Записать поток в файл вместо показа. Нужно, когда экрана под рукой нет:
// потом ffprobe скажет, валидное ли это видео и какого оно размера.
const VIDEO_FILE = arg('--zapis-videa', null)
// Аппаратный декодер малины. Если он капризничает, есть запасной путь.
const DECODER = flag('--programmnyy-dekoder') ? null : 'h264_v4l2m2m'
// Композитный тракт обрезает края — это оверскан, наследие кинескопов.
// Обрезка несимметричная: на этой машине режет сверху и слева. Поэтому
// отступы задаются по каждой стороне отдельно, в процентах от стороны.
// --polya задаёт все четыре сразу, остальные флаги уточняют по месту.
// Значения берутся из флага, из переменной окружения или из общего --polya.
// Переменные нужны, чтобы подбирать отступы по месту, правя один файл
// настроек, а не код и не юнит systemd.
const marginPart = (name, envName) => {
  const common = process.env.POLYA ?? arg('--polya', 0)
  const value = Number(arg(name, process.env[envName] ?? common))
  return Math.min(Math.max(Number.isFinite(value) ? value : 0, 0), 40)
}
// Размер кадра композита. Поток от донгла в него не вписывается по
// пропорциям, и ffplay сам добавил бы поля сверху и снизу. Нам это не нужно:
// кадр PAL растягивается монитором на всю ширину, то есть поля — чистая
// потеря высоты. Поэтому масштабируем в размер кадра принудительно.
const SCREEN = (() => {
  const text = arg('--ekran', process.env.EKRAN ?? '720x576')
  const [w, h] = String(text).toLowerCase().split('x').map(Number)
  if (![w, h].every((v) => Number.isInteger(v) && v >= 2 && v <= 8192 && v % 2 === 0)) {
    throw new Error('--ekran: нужны положительные чётные размеры, например 720x576')
  }
  return { w, h }
})()

const MARGIN = {
  left: marginPart('--sleva', 'POLYA_SLEVA'),
  right: marginPart('--sprava', 'POLYA_SPRAVA'),
  top: marginPart('--sverhu', 'POLYA_SVERHU'),
  bottom: marginPart('--snizu', 'POLYA_SNIZU'),
}

// Журнал пишем в файл, а не полагаемся на journald: у пользовательских служб
// он на этой системе не сохраняется, и после перезагрузки разбираться было бы
// нечем. А разбираться придётся в гараже, где под рукой только телефон.
const LOG_DIR = process.env.BMW_LOG_DIR || `${process.env.HOME}/logi`
const LOG_FILE = `${LOG_DIR}/carplay.log`
const LOG_MAX = 5 * 1024 * 1024

let logStream = null
let logBytes = 0
let logRotating = false
function openLog() {
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true })
    logBytes = fs.existsSync(LOG_FILE) ? fs.statSync(LOG_FILE).size : 0
    if (logBytes >= LOG_MAX) {
      fs.renameSync(LOG_FILE, `${LOG_FILE}.1`)
      logBytes = 0
    }
    const stream = fs.createWriteStream(LOG_FILE, { flags: 'a' })
    logStream = stream
    stream.on('error', () => { if (logStream === stream) logStream = null })
  } catch {
    logStream = null
  }
}
openLog()

function writeLog(line) {
  if (!logStream || logRotating || logStream.writableNeedDrain) return
  // ponytail: при медленном диске пропускаем файловый журнал (console остаётся),
  // иначе отладка сама раздует очередь и станет мешать аудио.
  const text = line.slice(0, 8192) + '\n'
  if (logBytes + Buffer.byteLength(text) > LOG_MAX) {
    logRotating = true
    const previous = logStream
    logStream = null
    previous.end(() => {
      try { fs.renameSync(LOG_FILE, `${LOG_FILE}.1`) } catch { /* диск недоступен */ }
      openLog()
      logRotating = false
      // Если переименование не удалось, openLog повторит его или отключит файл.
      if (logStream) writeLog(line)
    })
    return
  }
  logBytes += Buffer.byteLength(text)
  logStream.write(text)
}

function stamp() {
  const d = new Date()
  const p = (n, w = 2) => String(n).padStart(w, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`
}

function log(...parts) {
  const line = `${stamp()} ${parts.join(' ')}`
  console.log(line)
  writeLog(line)
}

// Ошибки самой библиотеки идут в console.error мимо нас. Перехватываем,
// иначе в файле будет половина картины.
const origError = console.error.bind(console)
console.error = (...parts) => {
  const line = `${stamp()} ОШИБКА ${parts.map((p) => (p && p.stack) ? p.stack : String(p)).join(' ')}`
  origError(line)
  writeLog(line)
}

process.on('uncaughtException', (err) => {
  log('НЕОЖИДАННАЯ ОШИБКА:', err?.stack || err)
  process.exit(1)
})
process.on('unhandledRejection', (err) => {
  log('НЕОБРАБОТАННЫЙ ОТКАЗ:', err?.stack || err)
})

// --- показ картинки ----------------------------------------------------------

let player = null
let videoFile = null
let videoBytes = 0
let firstFrameLogged = false
// Пока в потоке не встретится заголовок последовательности, проигрывателю
// не отдаём ничего. Иначе он включается посреди кадра, ругается
// «non-existing PPS» и, если к нему прицеплен фильтр, не может определить
// размер картинки и вообще не открывает окно. Снаружи это выглядит как
// «работает через раз»: повезло с опорным кадром — показал, не повезло — нет.
let synced = false
let syncTail = Buffer.alloc(0)

// Заголовок последовательности H.264: стартовый код и тип элемента 7.
function findSequenceStart(data) {
  for (let i = 0; i + 3 < data.length; i++) {
    if (data[i] !== 0 || data[i + 1] !== 0) continue
    if (data[i + 2] === 1 && (data[i + 3] & 0x1f) === 7) return i
    if (data[i + 2] === 0 && data[i + 3] === 1 &&
        i + 4 < data.length && (data[i + 4] & 0x1f) === 7) return i
  }
  return -1
}

let playerFailedAt = 0
// Признак «останавливаем сами»: нужен, чтобы не считать свой же сигнал
// ошибкой и не поднимать окно заново там, где мы его нарочно закрыли.
let playerRetryTimer = null
let playerRefreshTimer = null

function writeVideo(chunk) {
  let data = chunk
  if (!synced) {
    const combined = syncTail.length ? Buffer.concat([syncTail, chunk]) : chunk
    const at = findSequenceStart(combined)
    if (at < 0) {
      // Держим хвост: стартовый код мог разорваться между порциями.
      syncTail = combined.subarray(Math.max(0, combined.length - 4))
      return
    }
    synced = true
    syncTail = Buffer.alloc(0)
    data = combined.subarray(at)
    log(`поймал начало последовательности, отдаю проигрывателю ${data.length} байт`)
  }
  videoBytes += data.length
  if (videoFile && !videoFile.write(data)) {
    videoFile.end()
    videoFile = null
    log('запись видео остановлена: диск не успевает')
  }
  // Показ мог упасть — например, служба стартовала раньше, чем поднялся X.
  // Кадры при этом продолжают идти, так что поднимаем его заново, но не чаще
  // раза в пять секунд, чтобы не молотить впустую при настоящей поломке.
  if (!player && !NO_VIDEO && !VIDEO_FILE && Date.now() - playerFailedAt > 5000) {
    log('показа нет, поднимаю заново')
    startPlayer()
  }
  if (player?.stdin.writableNeedDrain) {
    synced = false
    syncTail = Buffer.alloc(0)
    return
  }
  if (player) player.stdin.write(data)
}

function startPlayer() {
  if (VIDEO_FILE && !videoFile) {
    videoFile = fs.createWriteStream(VIDEO_FILE, { flags: 'wx' })
    videoFile.on('error', (err) => { log('запись видео недоступна:', err.message); videoFile = null })
    log(`пишу видео в ${VIDEO_FILE}`)
  }
  if (NO_VIDEO || VIDEO_FILE || player) return
  const args = [
    '-hide_banner', '-loglevel', 'warning',
    // Подаём H.264 с SPS, поэтому длительная разведка потока не нужна.
    '-probesize', '32768', '-analyzeduration', '0',
    // nobuffer выбрасывает пакеты разведки, среди которых может быть первый
    // IDR. На неподвижном экране следующего опорного кадра можно не дождаться.
    '-flags', 'low_delay', '-framedrop', '-sync', 'ext',
  ]
  // У ffplay декодер задаётся ключом -vcodec. Ключ -c:v, привычный по ffmpeg,
  // он не понимает и молча завершается с ошибкой «Option not found».
  if (DECODER) args.push('-vcodec', DECODER)
  {
    // Фильтр ставим всегда, даже без полей: иначе ffplay вписывает кадр
    // с сохранением пропорций и добавляет чёрные полосы сверху и снизу.
    // Размеры считаем целыми числами заранее — выражения внутри фильтра
    // округляются каждое по-своему, и картинка выходит на пиксель больше
    // рамки. ffplay тогда падает с «Input area not within the padded area»,
    // окно не открывается, и снаружи это выглядит как «процесс жив, а
    // картинки нет». На это ушло три попытки.
    const even = (v) => Math.max(2, Math.round(v / 2) * 2)
    const innerW = even(SCREEN.w * (100 - MARGIN.left - MARGIN.right) / 100)
    const innerH = even(SCREEN.h * (100 - MARGIN.top - MARGIN.bottom) / 100)
    const x = Math.round(SCREEN.w * MARGIN.left / 100)
    const y = Math.round(SCREEN.h * MARGIN.top / 100)
    args.push('-vf',
      `scale=${innerW}:${innerH},pad=${SCREEN.w}:${SCREEN.h}:${x}:${y}:black,setsar=1`)
    log(`кадр ${SCREEN.w}x${SCREEN.h}, картинка ${innerW}x${innerH}, сдвиг ${x}, ${y}`)
  }
  // -alwaysontop обязателен, иначе любой клик мышью поднимает рабочий стол
  // поверх нашего окна, и снаружи это выглядит как «CarPlay не запускается»,
  // хотя процесс жив и кадры идут. -noborder убирает рамку окна.
  args.push('-alwaysontop', '-noborder', '-f', 'h264', '-i', 'pipe:0', '-fs', '-autoexit')
  clearTimeout(playerRetryTimer)
  player = spawn('ffplay', args, { stdio: ['pipe', 'ignore', 'pipe'] })
  // Сообщения ffplay забираем себе. Раньше они уходили в journald, который
  // тут ничего не хранит, и причина падения терялась безвозвратно.
  player.stderr.on('data', (chunk) => {
    const text = chunk.toString('utf8').trim()
    if (text) log('ffplay:', text)
  })
  const currentPlayer = player
  const failed = (reason) => {
    if (player !== currentPlayer) return
    log(`ffplay: ${reason}`)
    player = null
    currentPlayer.stdin.destroy()
    currentPlayer.kill('SIGTERM')
    playerFailedAt = Date.now()
    synced = false
    syncTail = Buffer.alloc(0)
    clearTimeout(playerRetryTimer)
    clearInterval(playerRefreshTimer)
    if (!stopping) playerRetryTimer = setTimeout(() => {
      if (!player && !stopping) startPlayer()
    }, 3000)
  }
  player.on('error', (err) => failed(err.message))
  player.on('exit', (code, signal) => failed(`завершился: код ${code}, сигнал ${signal}`))
  // Труба может закрыться раньше, чем мы перестанем писать. Это не повод падать.
  player.stdin.on('error', (err) => failed(err.message))
  player.stdin.on('drain', () => { if (player === currentPlayer && !synced) requestKeyframe() })
  log('ffplay запущен')
  // Просим донгл прислать опорный кадр. Без него проигрыватель стартует
  // посреди потока, ругается «non-existing PPS» и не может определить размер
  // картинки: следующий опорный кадр придёт сам, но ждать его нечего.
  requestKeyframe()
  // Восстанавливаем опорные кадры и при продолжении сеанса без Plugged.
  clearInterval(playerRefreshTimer)
  playerRefreshTimer = setInterval(requestKeyframe, 5000)
}

function stopPlayer() {
  if (videoFile) {
    videoFile.end()
    videoFile = null
    log(`видео записано, ${videoBytes} байт`)
  }
  clearTimeout(playerRetryTimer)
  clearInterval(playerRefreshTimer)
  if (!player) return
  const previous = player
  player = null
  previous.stdin.destroy()
  previous.kill('SIGTERM')
  log('ffplay остановлен нами')
  synced = false
  syncTail = Buffer.alloc(0)
}

// --- звук --------------------------------------------------------------------

// ponytail: два aplay используют уже настроенный ALSA plug/dmix: он смешивает
// потоки и приводит их к аппаратной частоте. hw: для двух потоков не годится.
const audioStreams = new Map()
const audioRetryAt = new Map()
const audioVolumes = new Map()
const AUDIO_DELAY_SECONDS = 0.5
const MAX_RATE_SHIFT = 0.006
const AUDIO_CHUNK_SECONDS = 0.02
// Пустая очередь — ещё не голодание. Ниже по цепочке (труба и буфер aplay)
// лежит до 0.7 с звука, и aplay забирает его рывками: очередь Node то копится
// секунду, то разом уходит почти вся. Телефон шлёт пакет каждые 65 мс, поэтому
// пока он присылает данные, ждём следующий пакет, а не подмешиваем тишину.
// Тишина — только если данных нет дольше этого времени. Проверено 03.10.2026.
const AUDIO_GAP_MS = 250
// Задаётся журналом очереди (--zhurnal-ocheredi) в конце файла.
let onQueueEvent = null
const AUDIO_FILE = arg('--zapis-zvuka', null)
let audioCapture = null
let audioCaptureBytes = 0
if (AUDIO_FILE) {
  audioCapture = fs.createWriteStream(AUDIO_FILE, { flags: 'wx', mode: 0o600, highWaterMark: 1024 * 1024 })
  audioCapture.on('error', (err) => {
    log('запись звука недоступна:', err.message)
    audioCapture = null
  })
}

function captureAudio(message) {
  if (!audioCapture) return
  const { decodeType, audioType, command, volume, volumeDuration, data } = message
  if (data?.byteLength > 1024 * 1024) return
  const pcm = ArrayBuffer.isView(data)
    ? Buffer.from(data.buffer, data.byteOffset, data.byteLength) : null
  const line = JSON.stringify({ ms: performance.now(), decodeType, audioType,
    command, volume, volumeDuration, pcm: pcm?.toString('base64') }) + '\n'
  audioCaptureBytes += Buffer.byteLength(line)
  // ponytail: одна запись до 32 МиБ; при медленном диске прекращаем запись,
  // не задерживая USB и звук. Для долгого исследования нужен внешний рекордер.
  if (audioCaptureBytes > 32 * 1024 * 1024) {
    audioCapture.end()
    audioCapture = null
    log('запись звука остановлена: предел 32 МиБ')
  } else if (!audioCapture.write(line)) {
    audioCapture.end()
    audioCapture = null
    log('запись звука остановлена: диск не успевает')
  }
}

function stopAudio(type) {
  const stream = audioStreams.get(type)
  if (!stream) return
  audioStreams.delete(type) // запоздалый exit не должен затронуть новый поток
  clearTimeout(stream.gapTimer)
  stream.source.destroy()
  stream.sink.destroy()
  stream.child.stdin.destroy()
  stream.child.kill('SIGTERM')
}

function stopAllAudio() {
  for (const type of audioStreams.keys()) stopAudio(type)
  audioVolumes.clear()
  audioRetryAt.clear()
}

function pushAudio(stream, buffer) {
  stream.lastDataAt = performance.now()
  if (!stream.pending.length) stream.queuedAt = stream.lastDataAt
  stream.ended = false
  stream.received += buffer.length
  const limit = stream.target * 2
  // Не копируем огромный всплеск целиком. Обрезка всегда по границе PCM-кадра.
  if (stream.pending.length + buffer.length > limit) {
    const keep = stream.target
    stream.pending = buffer.length >= keep ? Buffer.from(buffer.subarray(-keep))
      : Buffer.concat([stream.pending.subarray(-(keep - buffer.length)), buffer])
    stream.phase = 0
    stream.drops++
    onQueueEvent?.(stream, 'обрезка')
  } else {
    stream.pending = Buffer.concat([stream.pending, buffer])
  }
  if (stream.waiting) resumeAudio(stream)
}

// Readable ждёт данных: read() ничего не отдал. Продолжаем по приходу пакета,
// по OUTPUT_STOP или, если телефон замолчал, через AUDIO_GAP_MS.
function waitAudio(stream) {
  stream.waiting = true
  clearTimeout(stream.gapTimer)
  stream.gapTimer = setTimeout(() => resumeAudio(stream), AUDIO_GAP_MS)
}

function resumeAudio(stream) {
  stream.waiting = false
  clearTimeout(stream.gapTimer)
  if (stream.source.destroyed) return
  const chunk = takeAudio(stream, stream.chunkBytes)
  if (chunk) stream.source.push(chunk)
  else waitAudio(stream)
}

function takeAudio(stream, outBytes) {
  const { frameBytes, rate } = stream
  const outFrames = outBytes / frameBytes
  const out = Buffer.alloc(outBytes)
  if (!stream.primed) {
    if (!stream.pending.length) return out
    // Даже короткое уведомление начнёт играть через полсекунды, не ожидая
    // недостижимого для него размера очереди. OUTPUT_STOP позволяет начать раньше.
    if (stream.pending.length < stream.target && !stream.ended &&
        performance.now() - stream.queuedAt < AUDIO_DELAY_SECONDS * 1000) return out
    stream.primed = true
    stream.fadeIn = Math.round(rate * 0.005)
  }
  const haveFrames = stream.pending.length / frameBytes
  const error = (stream.pending.length - stream.target) / stream.target
  const ratio = 1 + Math.max(-MAX_RATE_SHIFT, Math.min(MAX_RATE_SHIFT, error * 0.05))
  // null — «подожди»: см. AUDIO_GAP_MS. +1 кадр нужен для интерполяции.
  if (haveFrames < Math.ceil(stream.phase + outFrames * ratio) + 1 && !stream.ended &&
      performance.now() - stream.lastDataAt < AUDIO_GAP_MS) return null
  let pos = stream.phase
  let produced = 0
  for (; produced < outFrames && pos < haveFrames; produced++, pos += ratio) {
    const idx = Math.floor(pos)
    const frac = pos - idx
    const next = Math.min(idx + 1, haveFrames - 1)
    if (stream.gainFrames > 0) {
      stream.gain += (stream.gainTarget - stream.gain) / stream.gainFrames--
    }
    const fadeFrames = Math.max(1, Math.round(rate * 0.005))
    const fade = stream.fadeIn > 0 ? 1 - stream.fadeIn-- / fadeFrames : 1
    for (let ch = 0; ch < frameBytes / 2; ch++) {
      const a = stream.pending.readInt16LE(idx * frameBytes + ch * 2)
      const b = stream.pending.readInt16LE(next * frameBytes + ch * 2)
      out.writeInt16LE(Math.round((a + (b - a) * frac) * stream.gain * fade),
        produced * frameBytes + ch * 2)
    }
  }
  const consumed = Math.min(Math.floor(pos), haveFrames)
  stream.pending = stream.pending.subarray(consumed * frameBytes)
  stream.phase = pos - consumed
  if (produced < outFrames || !stream.pending.length) {
    // Голодание завершает волну один раз. Нельзя оставить один отсчёт и
    // сбросить phase: тогда он повторяется каждые 20 мс бесконечно.
    const tail = Math.min(produced, Math.max(1, Math.round(rate * 0.005)))
    for (let i = 0; i < tail; i++) {
      for (let ch = 0; ch < frameBytes / 2; ch++) {
        const at = (produced - tail + i) * frameBytes + ch * 2
        out.writeInt16LE(Math.round(out.readInt16LE(at) * (tail - i - 1) / tail), at)
      }
    }
    stream.pending = Buffer.alloc(0)
    stream.phase = 0
    stream.primed = false
    stream.underruns++
    onQueueEvent?.(stream, 'опустошение')
  }
  return out
}

function setAudioVolume(type, volume, seconds) {
  if (!Number.isFinite(volume) || volume < 0 || volume > 1 ||
      !Number.isFinite(seconds) || seconds < 0 || seconds > 10) return
  audioVolumes.set(type, { volume, seconds })
  const stream = audioStreams.get(type)
  if (!stream) return
  stream.gainTarget = volume
  stream.gainFrames = Math.round(seconds * stream.rate)
  if (!stream.gainFrames) stream.gain = volume
}

function playAudio(message) {
  if (!message || typeof message !== 'object') return
  captureAudio(message)
  const type = message.audioType
  // 1 — основной выход, 2 — навигация/уведомления; 3 — микрофон, не выход.
  if (![1, 2].includes(type)) return
  if (message.volumeDuration != null) {
    setAudioVolume(type, message.volume, message.volumeDuration)
    log(`громкость потока ${type}: ${message.volume}, переход ${message.volumeDuration} с`)
    return
  }
  if (message.command != null) {
    log(`аудиокоманда ${AudioCommand[message.command] || message.command}, поток ${type}, формат ${message.decodeType}`)
    const stream = audioStreams.get(type)
    // Команды могут относиться к прежнему формату (например, media после Siri).
    // OUTPUT_STOP — конец подачи, а не повод уничтожить ещё не сыгранный хвост.
    if (message.command === AudioCommand.AudioOutputStop &&
        stream?.decodeType === message.decodeType) {
      stream.ended = true
      if (stream.waiting) resumeAudio(stream) // доиграть хвост с затуханием
    }
    // Микрофонные команды исполняет CarplayNode; остальные — информационные.
    return
  }
  const format = decodeTypeMap[message.decodeType]
  const data = message.data
  if (!format || format.bitrate !== 16 || !ArrayBuffer.isView(data) ||
      !data.byteLength || data.byteLength > 1024 * 1024 || data.byteLength % (format.channel * 2)) {
    log(`пропускаю некорректный PCM: decodeType=${message.decodeType}, поток=${type}`)
    return
  }
  let stream = audioStreams.get(type)
  if (stream && stream.decodeType !== message.decodeType) {
    stopAudio(type)
    stream = null
  }
  if (!stream) {
    if (performance.now() < (audioRetryAt.get(type) || 0)) return
    const rate = format.frequency
    const frameBytes = format.channel * 2
    const child = spawn('aplay', [
      '-t', 'raw', '-f', 'S16_LE', '-r', String(rate), '-c', String(format.channel),
      // На живом WM8960 period_time округляется до 125 мс. Запрос 200 мс
      // даёт лишь два периода; 500 мс позволяет использовать все три (375 мс).
      '-D', AUDIO_DEVICE, '--buffer-time=500000', '--period-time=40000',
    ], { stdio: ['pipe', 'ignore', 'pipe'] })
    const gain = audioVolumes.get(type)?.volume ?? 1
    stream = { child, decodeType: message.decodeType, rate, frameBytes,
      pending: Buffer.alloc(0), phase: 0, primed: false, queuedAt: 0, ended: false,
      target: Math.round(rate * AUDIO_DELAY_SECONDS) * frameBytes,
      gain, gainTarget: gain, gainFrames: 0, fadeIn: 0,
      received: 0, drops: 0, underruns: 0, measuredAt: performance.now() }
    const chunkBytes = Math.round(rate * AUDIO_CHUNK_SECONDS) * frameBytes
    stream.chunkBytes = chunkBytes
    const current = stream
    // Стандартный pipe прекращает чтение при write(false) и ждёт drain.
    // Темп задаёт потребление aplay/ALSA, а не независимый таймер Node.
    stream.source = new Readable({ highWaterMark: chunkBytes,
      read() {
        const chunk = takeAudio(current, chunkBytes)
        if (chunk) this.push(chunk)
        else waitAudio(current)
      } })
    audioStreams.set(type, stream)
    const failed = (reason) => {
      if (audioStreams.get(type) !== current) return
      log(`aplay поток ${type}: ${reason}`)
      stopAudio(type)
      audioRetryAt.set(type, performance.now() + 3000)
    }
    child.on('error', (err) => failed(err.message))
    child.stdin.on('error', (err) => failed(err.message))
    child.on('exit', (code, signal) => failed(`завершился: код ${code}, сигнал ${signal}`))
    child.stderr.on('data', (chunk) => log(`aplay поток ${type}:`, chunk.toString().trim()))
    stream.source.on('error', (err) => failed(err.message))
    // Ограничиваем ещё и Node-очередь stdin одной порцией: его стандартный
    // highWaterMark может вместить секунды моно. Остальной запас — трубы ОС/ALSA.
    stream.sink = new Writable({ highWaterMark: chunkBytes,
      write(chunk, encoding, done) { child.stdin.write(chunk, done) } })
    stream.sink.on('error', (err) => failed(err.message))
    stream.source.pipe(stream.sink)
    log(`aplay запущен: поток ${type}, ${rate}:${format.channel}, устройство ${AUDIO_DEVICE}`)
  }
  pushAudio(stream, Buffer.from(data.buffer, data.byteOffset, data.byteLength))
}

const audioStatsTimer = setInterval(() => {
  for (const [type, stream] of audioStreams) {
    const now = performance.now()
    const incoming = Math.round(stream.received * 1000 / (now - stream.measuredAt))
    log(`звук ${type}/${stream.decodeType}: очередь ${stream.pending.length}/${stream.target}, ` +
      `вход ${incoming} Б/с, номинал ${stream.rate * stream.frameBytes}, ` +
      `обрезки ${stream.drops}, опустошения ${stream.underruns}`)
    stream.measuredAt = now
    stream.received = 0
  }
}, 5000)

// --- сокет -------------------------------------------------------------------

const clients = new Set()
let phoneConnected = false

function announce(client) {
  const line = JSON.stringify({ event: 'phone', connected: phoneConnected }) + '\n'
  const targets = client ? [client] : clients
  for (const c of targets) {
    if (c.writableLength > 8192) { c.destroy(); continue }
    try { c.write(line) } catch { c.destroy() }
  }
}

function setPhone(connected) {
  if (connected === phoneConnected) return
  phoneConnected = connected
  log(connected ? 'телефон подключился' : 'телефон отключился')
  announce()
}

const server = net.createServer((client) => {
  if (clients.size >= 16) { client.destroy(); return }
  client.setEncoding('utf8')
  clients.add(client)
  log('подключился клиент')
  announce(client)
  let buffer = ''
  client.on('data', (chunk) => {
    buffer += chunk
    let nl
    while ((nl = buffer.indexOf('\n')) >= 0) {
      if (Buffer.byteLength(buffer.slice(0, nl)) > 4096) { client.destroy(); return }
      const line = buffer.slice(0, nl)
      buffer = buffer.slice(nl + 1)
      try { handle(line) } catch (err) { log('ошибка команды:', err.message) }
    }
    if (Buffer.byteLength(buffer) > 4096) client.destroy()
  })
  const drop = () => { clients.delete(client); log('клиент отключился') }
  client.on('close', drop)
  client.on('error', drop)
})

async function startSocket() {
  // Проверяем живой процесс, прежде чем удалить оставшийся после аварии сокет.
  let existing
  try { existing = fs.lstatSync(SOCKET) } catch (err) {
    if (err.code !== 'ENOENT') throw err
  }
  if (existing) {
    if (!existing.isSocket() || existing.uid !== process.getuid()) {
      throw new Error(`путь сокета занят чужим объектом: ${SOCKET}`)
    }
    await new Promise((resolve, reject) => {
      const probe = net.createConnection(SOCKET)
      probe.setTimeout(1000, () => { probe.destroy(); reject(new Error('сокет не отвечает')) })
      probe.on('connect', () => { probe.destroy(); reject(new Error('CarPlay уже запущен')) })
      probe.on('error', (err) => {
        if (err.code === 'ECONNREFUSED' || err.code === 'ENOENT') resolve()
        else reject(err)
      })
    })
    try {
      const current = fs.lstatSync(SOCKET)
      if (current.ino !== existing.ino || current.dev !== existing.dev) {
        throw new Error('сокет изменился во время проверки')
      }
      fs.unlinkSync(SOCKET)
    } catch (err) { if (err.code !== 'ENOENT') throw err }
  }
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(SOCKET, () => {
      server.removeListener('error', reject)
      fs.chmodSync(SOCKET, 0o600)
      log(`слушаю ${SOCKET}`)
      log(`журнал пишется в ${LOG_FILE}`)
      resolve()
    })
  })
}
server.on('error', (err) => log('ошибка сокета:', err.message))

// --- команды -----------------------------------------------------------------

let carplay = null

function key(name) {
  if (!carplay) return
  carplay.sendKey(name)
}

function handle(line) {
  let message
  try { message = JSON.parse(line) } catch { return }
  if (!message || typeof message !== 'object' || Array.isArray(message) ||
      typeof message.cmd !== 'string') return
  switch (message.cmd) {
    case 'navigate': {
      const steps = message.steps ?? 1
      if (!Number.isInteger(steps) || steps < 1 || steps > 10 || typeof message.right !== 'boolean') return
      for (let i = 0; i < steps; i++) key(message.right ? 'right' : 'left')
      log(`команда: ${message.right ? 'вправо' : 'влево'} на ${steps}`)
      break
    }
    case 'select': {
      const current = carplay
      key('selectDown')
      setTimeout(() => { if (current === carplay) key('selectUp') }, 60)
      log('команда: выбор')
      break
    }
    case 'back':
      key('back')
      log('команда: назад')
      break
    case 'home':
      key('home')
      log('команда: домой')
      break
    case 'next':
      key('next')
      log('команда: следующий трек')
      break
    case 'prev':
      key('prev')
      log('команда: предыдущий трек')
      break
    case 'play':
      key('play')
      log('команда: играть')
      break
    case 'pause':
      key('pause')
      log('команда: пауза')
      break
    case 'touch': {
      // Отладочный примитив: ткнуть в экран. Координаты нормированные,
      // от 0 до 1, поэтому от разрешения не зависят. Из трёх действий
      // складывается и перетаскивание: down, несколько move, up.
      const actions = { down: TouchAction.Down, move: TouchAction.Move, up: TouchAction.Up }
      const action = actions[message.action]
      if (!Object.hasOwn(actions, message.action)) {
        log(`неизвестное действие касания: ${message.action}`)
        break
      }
      const { x, y } = message
      if (![x, y].every((v) => Number.isFinite(v) && v >= 0 && v <= 1)) return
      carplay?.dongleDriver.send(new SendTouch(x, y, action))
      log(`касание: ${message.action} в ${x.toFixed(3)}, ${y.toFixed(3)}`)
      break
    }
    default:
      log(`неизвестная команда: ${line}`)
  }
}

// --- донгл -------------------------------------------------------------------
//
// Донгл, которому никто не ответил, через несколько секунд уходит в сброс сам:
// в логе ядра видно подключение и отключение примерно раз в тринадцать секунд.
// Поэтому мало открыть его один раз — надо ловить каждое появление и, если
// рукопожатие не удалось, спокойно пробовать снова.

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

let stopping = false
let attempt = 0
let pairTimer = null
let resetOnRetry = false
let lastUsbReset = -Infinity
const PAIR_SECONDS = Number(arg('--poisk-kazhdye', 15))
if (!Number.isFinite(PAIR_SECONDS) || PAIR_SECONDS < 1 || PAIR_SECONDS > 3600) {
  throw new Error('--poisk-kazhdye: допустимо 1–3600 секунд')
}

async function session() {
  const current = new CarplayNode({ width: WIDTH, height: HEIGHT, fps: FPS })
  carplay = current
  current.onmessage = (ev) => {
    if (carplay !== current || stopping) return
    switch (ev.type) {
      case 'plugged':
        current.clearFrameInterval() // запросами опорных кадров занимается наш проигрыватель
        clearPair()
        startPlayer()
        setPhone(true)
        // Дневную тему просим именно здесь, а не при установке сеанса:
        // до подключения телефона просить некого, команда уходит впустую.
        if (!NIGHT) setTimeout(() => { if (carplay === current) key('disableNightMode') }, 1500)
        break
      case 'unplugged':
        stopAllAudio()
        startPair()
        setPhone(false)
        firstFrameLogged = false
        synced = false
        syncTail = Buffer.alloc(0)
        // Окно намеренно не трогаем. Убивать и создавать его заново на каждое
        // подключение телефона — это и есть источник пустого экрана и задержки:
        // пока оно создаётся и захватывает экран, проходит заметное время.
        // Пусть живёт, пока жив сеанс с донглом; без кадров оно просто замрёт.
        break
      case 'failure':
        log('донгл сообщил об ошибке')
        resetOnRetry = true
        wakeDetach()
        setPhone(false)
        break
      case 'video':
        clearPair()
        if (ev.message?.data) {
          // После перезапуска хоста донгл может продолжить поток без Plugged.
          setPhone(true)
          if (!firstFrameLogged) {
            firstFrameLogged = true
            log('пошли кадры видео')
          }
          writeVideo(ev.message.data)
        }
        break
      case 'audio':
        if (ev.message?.data?.byteLength) { clearPair(); setPhone(true) }
        playAudio(ev.message)
        break
      default:
        break
    }
  }
  // Собственный старт вместо carplay.start().
  //
  // Штатный start() сначала сбрасывает устройство, ждёт три секунды и ищет
  // его заново. Наш донгл в это же время уходит в сброс сам, раз в тринадцать
  // секунд, и два сброса сталкиваются: reset падает с LIBUSB_ERROR_NOT_FOUND.
  // Нам сброс не нужен — мы стартуем сразу после появления устройства,
  // оно и так только что перечислилось.
  const device = await webusb.requestDevice({ filters: DongleDriver.knownDevices })
  if (!device) throw new Error('устройство исчезло, пока мы к нему шли')
  await device.open()
  // При тёплом перезапуске IN может остаться посреди USB-пакета (babble).
  // clearHalt это не исправляет. Сбрасываем только после отказа чтения,
  // а не на каждом подключении; reset может завершиться NOT_FOUND при переучёте.
  if (resetOnRetry && performance.now() - lastUsbReset >= 30000) {
    resetOnRetry = false
    lastUsbReset = performance.now()
    log('восстанавливаю USB после отказа: однократный сброс донгла')
    try { await device.reset() }
    finally { try { await device.close() } catch { /* устройство переучитывается */ } }
    throw new Error('донгл сброшен, жду повторного подключения')
  }
  if (stopping || carplay !== current) { await device.close(); return }
  const config = Object.assign({}, DEFAULT_CONFIG, { width: WIDTH, height: HEIGHT, fps: FPS })
  await current.dongleDriver.initialise(device)
  if (stopping || carplay !== current) { await current.stop(); return }
  await current.dongleDriver.start(config)
  if (stopping || carplay !== current) { await current.stop(); return }
  // Окно поднимаем сразу, не дожидаясь телефона: пока оно создаётся и
  // захватывает экран, проходит заметное время, и ждать этого в момент
  // подключения незачем. Кадров ещё нет, ffplay спокойно ждёт их из трубы.
  startPlayer()

  // Штатный carplay.start(), который мы обходим из-за сброса, ставил ещё и
  // таймер сопряжения: если телефон не подключился сам, донглу отправляется
  // команда искать его по Wi-Fi. Без этого донгл ждёт вечно, когда телефон
  // не помнит его или ушёл на другую сеть. Возвращаем таймер руками.
  if (!phoneConnected) startPair()
}

function startPair() {
  clearPair()
  pairTimer = setInterval(() => {
    if (!carplay || phoneConnected || stopping) return
    log('телефона нет, прошу донгл поискать')
    carplay.dongleDriver.send(new SendCommand('wifiPair'))
  }, PAIR_SECONDS * 1000)
}

function requestKeyframe() {
  try {
    carplay?.dongleDriver.send(new SendCommand('frame'))
  } catch (err) {
    log('не удалось попросить опорный кадр:', err?.message || err)
  }
}

function clearPair() {
  if (pairTimer) {
    clearInterval(pairTimer)
    pairTimer = null
  }
}

async function teardown() {
  clearPair()
  setPhone(false)
  const previous = carplay
  carplay = null
  if (previous) previous.onmessage = null
  stopAllAudio()
  firstFrameLogged = false
  synced = false
  syncTail = Buffer.alloc(0)
  try { await Promise.race([previous?.stop(), sleep(2000)]) } catch { /* уже мёртв */ }
}

async function supervise() {
  log(`запрашиваю ${WIDTH}x${HEIGHT} при ${FPS} кадрах в секунду`)
  while (!stopping) {
    attempt += 1
    if (!(await waitForAttach())) {
      if (attempt <= 2) log('донгл не появляется, жду дальше')
      continue
    }
    // Дать устройству устояться после перечисления.
    await sleep(250)
    if (stopping) break
    const generation = detachGeneration
    let startupTimer
    try {
      const ended = waitForDetach(generation)
      await Promise.race([
        session(),
        ended.then(() => { throw new Error('донгл отключился или отказал во время запуска') }),
        new Promise((_, reject) => {
          startupTimer = setTimeout(() => reject(new Error('запуск донгла занял больше 10 секунд')), 10000)
        }),
      ])
      clearTimeout(startupTimer)
      log('сеанс с донглом установлен')
      attempt = 0
      // Пока сеанс жив, здесь делать нечего. Библиотека сама зовёт onmessage.
      // Ждём, пока донгл не пропадёт: это увидит обработчик detach ниже.
      await ended
      log('донгл пропал')
    } catch (err) {
      const text = err?.message || String(err)
      // Первые попытки шумят в одно и то же: донгл успел уйти в сброс.
      if (attempt <= 3 || attempt % 10 === 0) log(`не поднялся (${attempt}): ${text}`)
    }
    clearTimeout(startupTimer)
    detachResolver?.()
    await teardown()
    if (stopping) break
    // Если устройство ещё на месте, значит наша попытка была неудачной сама
    // по себе. Ждём его исчезновения, чтобы следующий заход попал в свежее окно.
    if (donglePresent()) {
      await waitForDetach(detachGeneration, 6000)
    }
    await sleep(300)
  }
}

let detachResolver = null
let detachGeneration = 0
let attachResolver = null

function wakeDetach() {
  detachGeneration++
  detachResolver?.()
}

function waitForDetach(generation = detachGeneration, timeout) {
  if (stopping || generation !== detachGeneration || !donglePresent()) return Promise.resolve()
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer)
      if (detachResolver === done) detachResolver = null
      resolve()
    }
    const timer = timeout == null ? null : setTimeout(done, timeout)
    detachResolver = done
  })
}

const isDongle = (device) => {
  const d = device.deviceDescriptor
  return DongleDriver.knownDevices.some((known) =>
    d.idVendor === known.vendorId && d.idProduct === known.productId)
}

const donglePresent = () => usb.getDeviceList().some(isDongle)

// Донгл живёт секунд девять и уходит в сброс. Попытка вслепую попадает то
// в начало этого окна, то в конец, и во втором случае рукопожатие не успевает.
// Поэтому ждём именно появления устройства и стартуем сразу за ним.
function waitForAttach(timeout = 20000) {
  if (donglePresent()) return Promise.resolve(true)
  return new Promise((resolve) => {
    const timer = setTimeout(() => { attachResolver = null; resolve(false) }, timeout)
    attachResolver = () => { clearTimeout(timer); resolve(true) }
  })
}

usb.on('attach', (device) => {
  if (isDongle(device) && attachResolver) {
    const resolve = attachResolver
    attachResolver = null
    resolve()
  }
})

usb.on('detach', (device) => { if (isDongle(device)) wakeDetach() })

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, async () => {
    if (stopping) return
    log('останавливаюсь')
    stopping = true
    if (detachResolver) { detachResolver(); detachResolver = null }
    if (attachResolver) { attachResolver(); attachResolver = null }
    const recordings = [audioCapture, videoFile, logStream].filter(Boolean)
    stopPlayer()
    stopAllAudio()
    clearInterval(audioStatsTimer)
    audioCapture?.end()
    // При остановке на лету драйвер иногда жалуется на незавершённый запрос.
    // На нас это не влияет: процесс всё равно уходит.
    await teardown()
    server.close()
    for (const client of clients) client.destroy()
    await Promise.race([
      Promise.all(recordings.map((stream) => new Promise((resolve) => {
        if (stream.writableFinished || stream.destroyed) { resolve(); return }
        stream.once('finish', resolve)
        stream.once('error', resolve)
        if (!stream.writableEnded) stream.end()
      }))),
      sleep(2000),
    ])
    process.exit(0)
  })
}

// Подробный журнал очереди для поиска пропаданий звука. Включается
// параметром --zhurnal-ocheredi <файл>; без него ничего не пишет.
// Строка: время мс, поток, очередь Б, буфер Readable, буфер sink,
// буфер stdin aplay, primed, обрезки, опустошения, задержка таймера мс.
const QUEUE_LOG = arg('--zhurnal-ocheredi', null)
if (QUEUE_LOG) {
  let queueLog = fs.createWriteStream(QUEUE_LOG, { flags: 'a' })
  queueLog.on('error', (err) => { log('журнал очереди недоступен:', err.message); queueLog = null })
  let expected = performance.now() + 100
  setInterval(() => {
    const now = performance.now()
    const lag = Math.round(now - expected)
    expected = now + 100
    for (const [type, st] of audioStreams) {
      queueLog?.write(`${Date.now()} ${type} ${st.pending.length} ${st.source.readableLength} ` +
        `${st.sink.writableLength} ${st.child.stdin.writableLength} ${st.primed ? 1 : 0} ` +
        `${st.drops} ${st.underruns} ${lag}\n`)
    }
  }, 100)
  onQueueEvent = (stream, what) => queueLog?.write(`${Date.now()} ! ${what} ` +
    `очередь ${stream.pending.length} stdin ${stream.child.stdin.writableLength}\n`)
  log('журнал очереди:', QUEUE_LOG)
}

startSocket().then(supervise).catch((err) => {
  log('надзор упал:', err?.message || err)
  process.exit(1)
})

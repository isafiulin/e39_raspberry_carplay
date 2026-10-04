// Без USB/aplay и сторонних библиотек: node carplay/audio-check.cjs
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const net = require('node:net')
const vm = require('node:vm')
const { EventEmitter, once } = require('node:events')
const { Readable, Writable } = require('node:stream')
const source = fs.readFileSync(`${__dirname}/index.js`, 'utf8')
const section = (from, to) => source.slice(source.indexOf(from), source.indexOf(to))
const turn = () => new Promise((resolve) => setImmediate(resolve))
// Контракт node-carplay 4.1.0: AudioData несёт decodeType, НЕ frequency/channel.
const decodeTypeMap = Object.fromEntries([
  [1, 44100, 2], [2, 44100, 2], [3, 8000, 1], [4, 48000, 2],
  [5, 16000, 1], [6, 24000, 1], [7, 16000, 2],
].map(([id, frequency, channel]) => [id, { frequency, channel, bitrate: 16 }]))
let now = 0
const children = []
const context = vm.createContext({
  Buffer, Readable, Writable, decodeTypeMap, AudioCommand: { AudioOutputStop: 2 },
  performance: { now: () => now }, AUDIO_DEVICE: 'carplay',
  arg(name, fallback) { return fallback }, log() {}, setInterval() {},
  setTimeout, clearTimeout,
  spawn(name, args) {
    const child = new EventEmitter()
    child.args = args
    child.writes = []
    child.callbacks = []
    child.stdin = new Writable({ highWaterMark: 32,
      write(chunk, encoding, done) { child.writes.push(chunk); child.callbacks.push(done) } })
    child.stderr = new EventEmitter()
    child.kill = () => { child.killed = true }
    children.push(child)
    return child
  },
})
vm.runInContext(section('// --- звук ', '// --- сокет'), context)
const run = (code) => vm.runInContext(code, context)
function message(decodeType, audioType = 1) {
  return { decodeType, audioType, volume: 0, data: new Int16Array(1000) }
}
function play(value) { context.message = value; run('playAudio(message)') }
function state(rate = 44100, channels = 2, frames = 10000) {
  return { rate, frameBytes: channels * 2, pending: Buffer.alloc(frames * channels * 2),
    target: Math.round(rate * 0.5) * channels * 2, phase: 0, primed: true,
    queuedAt: now, gain: 1, gainTarget: 1, gainFrames: 0, fadeIn: 0,
    underruns: 0, received: 0, drops: 0 }
}
function take(s, frames = 882) {
  context.testState = s; context.outBytes = frames * s.frameBytes
  return run('takeAudio(testState, outBytes)')
}
async function check() {
  for (const [id, format] of Object.entries(decodeTypeMap)) {
    play(message(Number(id)))
    const child = children.at(-1)
    assert.equal(child.args[child.args.indexOf('-r') + 1], String(format.frequency))
    assert.equal(child.args[child.args.indexOf('-c') + 1], String(format.channel))
  }
  const main = run('audioStreams.get(1)')
  play(message(5, 2))
  const nav = run('audioStreams.get(2)')
  assert.equal(run('audioStreams.get(1)'), main)
  assert.notEqual(main, nav)
  play(message(5, 3))
  assert.equal(run('audioStreams.size'), 2)
  play({ ...message(99), frequency: 44100, channel: 2 })
  assert.equal(run('audioStreams.get(1)'), main) // неизвестный тип не маскируется fallback
  const old = main.child
  play(message(4))
  const current = run('audioStreams.get(1)')
  old.emit('exit', 0)
  assert.equal(run('audioStreams.get(1)'), current)
  const before = current.pending.length
  play({ decodeType: 4, audioType: 1, data: Buffer.alloc(3) })
  assert.equal(current.pending.length, before)
  // Учитываем byteOffset, а не весь backing ArrayBuffer.
  const backing = Buffer.alloc(24, 99)
  backing.fill(0, 4, 20)
  play({ decodeType: 4, audioType: 1, data: backing.subarray(4, 20) })
  assert.ok(current.pending.subarray(-16).every((b) => b === 0))

  for (const channels of [1, 2]) {
    const s = state(44100, channels)
    for (let i = 0; i < s.pending.length; i += 2) s.pending.writeInt16LE(12345, i)
    const output = take(s)
    for (let i = 0; i < output.length; i += 2) assert.equal(output.readInt16LE(i), 12345)
  }
  for (const [frames, ratio] of [[12000, 0.994], [26000, 1.006]]) {
    const s = state(44100, 2, frames)
    for (let i = 0; i < frames; i++) {
      s.pending.writeInt16LE(i, i * 4); s.pending.writeInt16LE(-i, i * 4 + 2)
    }
    take(s)
    const output = take(s)
    assert.equal(output.readInt16LE(0), Math.round(882 * ratio))
    assert.equal(output.readInt16LE(2), -Math.round(882 * ratio))
  }
  // Регрессия: последний отсчёт не повторяется после голодания.
  const last = state(44100, 1, 1)
  last.pending.writeInt16LE(12000)
  take(last)
  assert.equal(last.pending.length, 0)
  for (let i = 0; i < 10; i++) assert.ok(take(last).every((b) => b === 0))
  // Короткое уведомление стартует по таймауту, затем доигрывает полностью.
  const short = state(44100, 1, 1000)
  short.primed = false
  for (let i = 0; i < short.pending.length; i += 2) short.pending.writeInt16LE(5000, i)
  assert.ok(take(short).every((b) => b === 0))
  assert.equal(short.pending.length, 2000)
  now += 500
  assert.ok(take(short).some((b) => b !== 0))
  take(short)
  assert.equal(short.pending.length, 0)
  assert.ok(take(short).every((b) => b === 0))
  // Мгновенно пустая очередь при живом потоке — ожидание, а не тишина.
  const gap = state(44100, 2, 100)
  gap.lastDataAt = now
  assert.equal(take(gap), null)
  assert.equal(gap.pending.length, 400)
  assert.equal(gap.underruns, 0)
  assert.equal(gap.primed, true)
  now += 249
  assert.equal(take(gap), null)
  now += 1
  assert.ok(take(gap).length > 0) // телефон молчит 250 мс: настоящее голодание
  assert.equal(gap.underruns, 1)
  const stop = state(44100, 2, 100)
  stop.lastDataAt = now
  stop.ended = true
  assert.ok(take(stop).length > 0) // OUTPUT_STOP доигрывает хвост сразу
  assert.equal(stop.underruns, 1)
  // Пришёл пакет — ожидающий поток продолжает без подмешанной тишины.
  const podhvachen = state(44100, 2, 100)
  const pushed = []
  podhvachen.lastDataAt = now
  podhvachen.chunkBytes = 882 * 4
  podhvachen.source = { destroyed: false, push(chunk) { pushed.push(chunk) } }
  context.testState = podhvachen
  run('waitAudio(testState)')
  context.packet = Buffer.alloc(2880 * 4, 7)
  run('pushAudio(testState, packet)')
  assert.equal(podhvachen.waiting, false)
  assert.equal(pushed.length, 1)
  assert.equal(pushed[0].length, 882 * 4)
  assert.equal(podhvachen.underruns, 0)
  clearTimeout(podhvachen.gapTimer)
  // Большой всплеск ограничен целевым запасом и не ломает кадры.
  context.testState = state()
  run('pushAudio(testState, Buffer.alloc(1000000))')
  assert.equal(context.testState.pending.length, context.testState.target)
  assert.equal(context.testState.pending.length % 4, 0)
  // Минута непрерывной подачи быстрее/медленнее выхода на 0.531%.
  for (const drift of [0.00531, -0.00531]) {
    const s = state(8000, 1, 4000)
    let incoming = 0
    context.testState = s
    for (let tick = 0; tick < 3000; tick++) {
      const total = Math.floor((tick + 1) * 160 * (1 + drift))
      context.packet = Buffer.alloc((total - incoming) * 2)
      incoming = total
      run('pushAudio(testState, packet)')
      take(s, 160)
    }
    assert.equal(s.drops, 0)
    assert.equal(s.underruns, 0)
    assert.ok(s.pending.length > s.target * 0.8 && s.pending.length < s.target * 1.2)
  }
  const fading = state(44100, 1)
  for (let i = 0; i < fading.pending.length; i += 2) fading.pending.writeInt16LE(10000, i)
  fading.gainTarget = 0.5
  fading.gainFrames = 882
  const faded = take(fading)
  assert.equal(faded.readInt16LE(881 * 2), 5000)

  // Управление не попадает в PCM; stop другого формата не закрывает текущий.
  play({ decodeType: 5, audioType: 1, command: 2 })
  assert.equal(current.ended, false)
  play({ decodeType: 4, audioType: 1, command: 2 })
  assert.equal(current.ended, true)
  play({ decodeType: 4, audioType: 1, volume: 0.1, volumeDuration: 0.5 })
  assert.equal(current.gainTarget, 0.1)
  assert.equal(current.gainFrames, 24000)
  play({ decodeType: 4, audioType: 1, volume: NaN, volumeDuration: 0.5 })
  assert.equal(current.gainTarget, 0.1)
  // Реальные Readable/Writable: получатель заблокирован, генерация останавливается.
  await turn()
  const writes = current.child.writes.length
  assert.equal(writes, 1)
  const queued = current.source.readableLength
  await turn()
  assert.equal(current.child.writes.length, writes)
  assert.equal(current.source.readableLength, queued)
  assert.ok(queued <= 48000 * 4 * 0.02)
  current.child.callbacks.shift()()
  await turn()
  assert.equal(current.child.writes.length, writes + 1)
  current.child.emit('error', new Error('test failure'))
  assert.equal(run('audioStreams.has(1)'), false)
  const count = children.length
  play(message(4))
  assert.equal(children.length, count) // пауза после отказа
  run('stopAllAudio()')

  // Видео: ошибка запуска обрабатывается, поздний exit не убивает новое окно.
  const videos = []
  const video = vm.createContext({ Buffer, Date, fs, VIDEO_FILE: null, NO_VIDEO: false,
    DECODER: null, SCREEN: { w: 720, h: 576 },
    MARGIN: { left: 0, right: 0, top: 0, bottom: 0 }, stopping: false,
    log() {}, requestKeyframe() {}, setTimeout() { return 1 }, clearTimeout() {},
    setInterval() { return 1 }, clearInterval() {},
    spawn(name, args) {
      const child = new EventEmitter()
      child.stdin = new EventEmitter()
      child.stdin.write = () => true
      child.stdin.destroy = () => {}
      child.stderr = new EventEmitter()
      child.kill = () => {}
      child.args = args
      videos.push(child)
      return child
    },
  })
  vm.runInContext(section('// --- показ картинки', '// --- звук '), video)
  const vid = (code) => vm.runInContext(code, video)
  vid('startPlayer()')
  const oldVideo = videos.at(-1)
  assert.ok(!oldVideo.args.includes('nobuffer'))
  assert.ok(!oldVideo.args.includes('-infbuf'))
  vid('stopPlayer(); startPlayer()')
  const newVideo = videos.at(-1)
  oldVideo.emit('exit', 123)
  assert.equal(vid('player'), newVideo)
  newVideo.emit('error', new Error('no ffplay'))
  assert.equal(vid('player'), null)
  vid('startPlayer(); player.stdin.writableNeedDrain = true')
  video.chunk = Buffer.from([0, 0, 0, 1, 0x67, 1, 2, 3])
  vid('writeVideo(chunk)')
  assert.equal(vid('synced'), false)
  vid('stopPlayer()')

  // Живой донгл после перезапуска хоста может не повторять Plugged.
  const resumed = vm.createContext({ Buffer, carplay: null, stopping: false, resetOnRetry: false, lastUsbReset: -Infinity,
    performance: { now: () => 60000 }, wakeDetach() {},
    WIDTH: 800, HEIGHT: 480, FPS: 20, DEFAULT_CONFIG: {}, NIGHT: false,
    firstFrameLogged: false, synced: false, syncTail: Buffer.alloc(0),
    phoneConnected: false, log() {}, clearPair() {}, startPair() {}, startPlayer() {},
    setTimeout() {}, writeVideo() {}, playAudio() {}, stopAllAudio() {},
    setPhone(value) { resumed.phoneConnected = value },
    DongleDriver: { knownDevices: [] },
    webusb: { async requestDevice() { return { async open() {}, async close() {} } } },
    CarplayNode: class { constructor() {
      this.dongleDriver = { async initialise() {}, async start() {} }
    } },
  })
  vm.runInContext(section('async function session()', 'function startPair()'), resumed)
  await vm.runInContext('session()', resumed)
  vm.runInContext('carplay.onmessage({type:"video", message:{data:Buffer.alloc(4)}})', resumed)
  assert.equal(resumed.phoneConnected, true)
  vm.runInContext('carplay.onmessage({type:"unplugged"})', resumed)
  assert.equal(resumed.phoneConnected, false)
  vm.runInContext('carplay.onmessage({type:"audio", message:{data:Buffer.alloc(4)}})', resumed)
  assert.equal(resumed.phoneConnected, true)
  vm.runInContext('carplay.onmessage({type:"failure"})', resumed)
  assert.equal(resumed.resetOnRetry, true)
  let resets = 0
  let closed = 0
  resumed.webusb.requestDevice = async () => ({ async open() {},
    async reset() { resets++ }, async close() { closed++ } })
  await assert.rejects(vm.runInContext('session()', resumed), /донгл сброшен/)
  assert.equal(resets, 1)
  assert.equal(closed, 1)
  assert.equal(resumed.resetOnRetry, false)

  // USB: ранний detach, failure при оставшемся USB и отмена ожидания по таймауту.
  const usb = new EventEmitter()
  let present = false
  usb.getDeviceList = () => present ? [{ deviceDescriptor: { idVendor: 1, idProduct: 2 } }] : []
  const lifecycle = vm.createContext({ usb, stopping: false, Promise, setTimeout, clearTimeout,
    DongleDriver: { knownDevices: [{ vendorId: 1, productId: 2 }] } })
  vm.runInContext(section('let detachResolver = null', 'for (const signal'), lifecycle)
  const life = (code) => vm.runInContext(code, lifecycle)
  await life('waitForDetach()')
  present = true
  life('wakeDetach()')
  await life('waitForDetach(0)')
  const waiting = life('waitForDetach()')
  life('wakeDetach()')
  await waiting
  await life('waitForDetach(detachGeneration, 1)')
  assert.equal(life('detachResolver'), null)

  // Настоящий Unix-сокет: не удаляем сокет живого процесса/обычный файл.
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'bmw-check-'))
  const socket = path.join(temp, 'carplay.sock')
  const sent = []
  const socketContext = vm.createContext({ Buffer, fs, net, process, SOCKET: socket, LOG_FILE: path.join(temp, "carplay.log"),
    log() {}, setTimeout, TouchAction: { Down: 14, Move: 15, Up: 16 },
    SendTouch: class { constructor(x, y, action) { this.x=x; this.y=y; this.action=action } },
    fakeCarplay: { sendKey: (key) => sent.push(key), dongleDriver: { send: (v) => sent.push(v) } } })
  vm.runInContext(section('// --- сокет', '// --- донгл'), socketContext)
  const sock = (code) => vm.runInContext(code, socketContext)
  try {
    fs.writeFileSync(socket, 'keep')
    await assert.rejects(sock('startSocket()'), /чужим объектом/)
    assert.equal(fs.readFileSync(socket, 'utf8'), 'keep')
    fs.unlinkSync(socket)
    const occupied = net.createServer()
    await new Promise((resolve) => occupied.listen(socket, resolve))
    await assert.rejects(sock('startSocket()'), /уже запущен/)
    await new Promise((resolve) => occupied.close(resolve))
    await sock('startSocket()')
    assert.equal(fs.statSync(socket).mode & 0o777, 0o600)
    sock('carplay = fakeCarplay')
    const client = net.createConnection(socket)
    await once(client, 'connect')
    client.resume()
    client.write('null\n[]\n{"cmd":"touch","action":"toString","x":0,"y":0}\n')
    client.write('{"cmd":"navigate","right":true,"steps":2}\n')
    await new Promise((resolve) => setTimeout(resolve, 20))
    assert.deepEqual(sent, ['right', 'right'])
    const closed = once(client, 'close')
    client.write('x'.repeat(4097))
    await closed
    await new Promise((resolve) => sock('server').close(resolve))

    // Запись аудио сохраняет заголовки и исходный PCM, не перезаписывает файл.
    const captureFile = path.join(temp, 'audio.jsonl')
    const capture = vm.createContext({ fs, Buffer, performance: { now: () => 42 },
      arg: () => captureFile, log() {}, setInterval() {} })
    vm.runInContext(section('// --- звук ', '// --- сокет'), capture)
    capture.message = { decodeType: 5, audioType: 2, volume: 0,
      data: new Int16Array([123, -123, 456]) }
    vm.runInContext('captureAudio(message)', capture)
    await new Promise((resolve) => vm.runInContext('audioCapture', capture).end(resolve))
    const record = JSON.parse(fs.readFileSync(captureFile, 'utf8'))
    assert.equal(record.decodeType, 5)
    assert.equal(record.ms, 42)
    assert.deepEqual(Buffer.from(record.pcm, 'base64'), Buffer.from(capture.message.data.buffer))
    const duplicate = vm.createContext({ fs, Buffer,
      arg: () => captureFile, log() {}, setInterval() {} })
    vm.runInContext(section('// --- звук ', '// --- сокет'), duplicate)
    await new Promise((resolve) => vm.runInContext('audioCapture', duplicate).once('close', resolve))
    assert.equal(JSON.parse(fs.readFileSync(captureFile, 'utf8')).ms, 42)

    // Ротация без перезапуска: запись переносится в .1, следующая идёт в новый файл.
    const logFile = path.join(temp, 'carplay.log')
    const logs = vm.createContext({ fs, Buffer, LOG_FILE: logFile, LOG_DIR: temp, LOG_MAX: 100 })
    vm.runInContext(section('let logStream = null', 'function stamp()'), logs)
    vm.runInContext('writeLog("a".repeat(80))', logs)
    await turn()
    vm.runInContext('writeLog("b".repeat(30))', logs)
    for (let i = 0; i < 100 && !fs.existsSync(logFile + '.1'); i++) {
      await new Promise((resolve) => setTimeout(resolve, 2))
    }
    await new Promise((resolve) => vm.runInContext('logStream', logs).end(resolve))
    assert.equal(fs.readFileSync(logFile + '.1', 'utf8'), 'a'.repeat(80) + '\n')
    assert.equal(fs.readFileSync(logFile, 'utf8'), 'b'.repeat(30) + '\n')
  } finally {
    sock('server').close()
    for (const c of sock('clients')) c.destroy()
    fs.rmSync(temp, { recursive: true, force: true })
  }
  console.log('Audio, backpressure, video, USB, socket, capture and log checks passed')
}
check().catch((err) => { console.error(err); process.exitCode = 1 })

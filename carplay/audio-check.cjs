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
let blocked = false
const children = []
const context = vm.createContext({
  Buffer, decodeTypeMap, AudioCommand: { AudioOutputStop: 2 },
  performance: { now: () => now }, AUDIO_DEVICE: 'carplay',
  arg(name, fallback) { return fallback }, log() {}, setInterval() {},
  setTimeout, clearTimeout,
  spawn(name, args) {
    assert.equal(name, 'aplay')
    const child = new EventEmitter()
    child.args = args
    child.writes = []
    child.callbacks = []
    child.stdin = new Writable({ highWaterMark: 32,
      write(chunk, encoding, done) {
        child.writes.push(Buffer.from(chunk))
        if (blocked) child.callbacks.push(done)
        else done()
      } })
    child.stdin.on('finish', () => child.emit('exit', 0))
    child.stderr = new EventEmitter()
    child.kill = () => { child.killed = true }
    children.push(child)
    return child
  },
})
vm.runInContext(section('// --- звук ', '// --- сокет'), context)
const run = (code) => vm.runInContext(code, context)
function message(decodeType, audioType = 1) {
  return { decodeType, audioType, data: new Int16Array([123, -123, 32767, -32768]) }
}
function play(value) { context.message = value; run('playAudio(message)') }
async function check() {
  for (const [id, format] of Object.entries(decodeTypeMap)) {
    play(message(Number(id)))
    const child = children.at(-1)
    assert.equal(child.args[child.args.indexOf('-r') + 1], String(format.frequency))
    assert.equal(child.args[child.args.indexOf('-c') + 1], String(format.channel))
    assert.deepEqual(child.writes[0], Buffer.from(message(Number(id)).data.buffer))
    await turn() // старый формат доигрывает EOF
  }
  run('stopAllAudio()')
  play(message(5))
  const main = run('audioStreams.get(1)')
  play(message(2, 2))
  const nav = run('audioStreams.get(2)')
  assert.notEqual(main, nav)
  const count = children.length
  play(message(5, 3))
  play(message(99))
  play({ decodeType: 5, audioType: 1, data: Buffer.alloc(3) })
  assert.equal(children.length, count)
  assert.equal(main.child.writes.length, 1)
  const backing = Buffer.alloc(24, 99)
  backing.fill(0, 4, 20)
  play({ decodeType: 5, audioType: 1, data: backing.subarray(4, 20) })
  assert.deepEqual(main.child.writes.at(-1), Buffer.alloc(16))

  // 1.2 с речи: начало и конец переданы побайтно, без ускорения и обрезки.
  const voice = Buffer.alloc(16000 * 2 * 1.2)
  for (let i = 0; i < voice.length / 2; i++) voice.writeInt16LE(i % 16000, i * 2)
  play({ decodeType: 5, audioType: 1, data: voice })
  assert.deepEqual(main.child.writes.at(-1), voice)
  now += 116
  play(message(5))
  assert.equal(main.maxGapMs, 116)
  main.child.stderr.emit('data', Buffer.from('under'))
  main.child.stderr.emit('data', Buffer.from('run!!! (at least 20 ms long)'))
  assert.equal(main.underruns, 1)
  main.child.stderr.emit('data', Buffer.from('another diagnostic'))
  assert.equal(main.underruns, 1)
  const writes = main.child.writes.length
  await turn()
  assert.equal(main.child.writes.length, writes) // тишина не синтезируется

  // Приглушение по команде сохраняет количество PCM-кадров и не меняет вход.
  play({ decodeType: 5, audioType: 1, volume: 0.5, volumeDuration: 0 })
  const original = message(5)
  play(original)
  const quiet = main.child.writes.at(-1)
  assert.equal(quiet.readInt16LE(0), 62)
  assert.equal(quiet.length, original.data.byteLength)
  assert.equal(original.data[0], 123)
  play({ decodeType: 5, audioType: 1, volume: NaN, volumeDuration: 0 })
  assert.equal(main.gainTarget, 0.5)
  play({ decodeType: 5, audioType: 1, volume: 1, volumeDuration: 4 / 16000 })
  play(original)
  assert.equal(main.child.writes.at(-1).readInt16LE(6), -32768)

  // STOP чужого формата не закрывает текущий; правильный даёт EOF и хвост.
  play({ decodeType: 2, audioType: 1, command: 2 })
  assert.equal(main.child.stdin.writableEnded, false)
  play({ decodeType: 5, audioType: 1, command: 2 })
  assert.equal(main.child.stdin.writableEnded, true)
  assert.equal(main.child.killed, undefined)
  await turn()
  assert.equal(run('audioPlayers.has(audioStreams.get(2))'), true)
  run('stopAllAudio()')

  // Медленный получатель: Writable хранит все пакеты в порядке, EOF ждёт их.
  blocked = true
  play(message(5))
  const slow = children.at(-1)
  const expected = [Buffer.from(message(5).data.buffer)]
  for (let i = 0; i < 8; i++) {
    const packet = Buffer.alloc(640, i)
    expected.push(Buffer.from(packet))
    play({ decodeType: 5, audioType: 1, data: packet })
    packet.fill(255) // буфер USB переиспользован
  }
  play({ decodeType: 5, audioType: 1, command: 2 })
  assert.equal(slow.stdin.writableFinished, false)
  // Новый формат может стартовать, поздний exit прежнего его не удаляет.
  play(message(2))
  const newer = run('audioStreams.get(1)')
  while (slow.callbacks.length) slow.callbacks.shift()()
  await turn()
  assert.deepEqual(Buffer.concat(slow.writes), Buffer.concat(expected))
  assert.equal(slow.stdin.writableFinished, true)
  assert.equal(slow.killed, undefined)
  assert.equal(run('audioStreams.get(1)'), newer)
  newer.child.emit('error', new Error('test failure'))
  assert.equal(run('audioStreams.has(1)'), false)
  const failedCount = children.length
  play(message(2))
  assert.equal(children.length, failedCount)
  run('stopAllAudio()')

  // Зависший выход ограничен по памяти и сообщает отказ вместо скрытой обрезки.
  play(message(5))
  const stuck = children.at(-1)
  play({ decodeType: 5, audioType: 1, data: Buffer.alloc(16000 * 2 * 4) })
  assert.equal(stuck.killed, true)
  assert.equal(run('audioPlayers.size'), 0)
  run('stopAllAudio()')
  blocked = false

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

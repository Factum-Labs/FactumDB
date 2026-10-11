// Exercise the actual React controls in local headless Chrome; no browser-library dependency.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve, sep } from 'node:path'
import { build } from 'esbuild'

const browser = process.env.FACTUMDB_BROWSER ?? [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
].find(existsSync)
assert.ok(browser, 'Set FACTUMDB_BROWSER to a Chrome-compatible executable.')
const bundled = await build({ entryPoints: ['checks/settings.browser.tsx'], bundle: true, platform: 'browser', format: 'iife', jsx: 'automatic', write: false, define: { 'process.env.NODE_ENV': '"development"' } })
const script = bundled.outputFiles[0].text
const assets = resolve('dist/assets')
const css = readFileSync(join(assets, readdirSync(assets).find(name => name.endsWith('.css'))), 'utf8')
const server = createServer((request, response) => {
  response.setHeader('Content-Type', (request.url === '/test.js' ? 'application/javascript' : request.url === '/style.css' ? 'text/css' : 'text/html') + '; charset=utf-8')
  response.end(request.url === '/test.js' ? script : request.url === '/style.css' ? css : '<!doctype html><link rel="stylesheet" href="/style.css"><div id="root"></div><script src="/test.js"></script>')
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const profile = mkdtempSync(join(tmpdir(), 'factumdb-settings-browser-'))
const processHandle = spawn(browser, ['--headless', '--disable-gpu', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', 'about:blank'], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] })
let socket
try {
  const browserUrl = await new Promise((resolve, reject) => {
    let log = ''
    const deadline = setTimeout(() => reject(new Error('Headless browser startup timed out')), 20000)
    processHandle.once('error', error => { clearTimeout(deadline); reject(error) })
    processHandle.stderr.on('data', chunk => { log += chunk; const match = log.match(/DevTools listening on (ws:\/\/\S+)/); if (match) { clearTimeout(deadline); resolve(match[1]) } })
  })
  const debugHost = new URL(browserUrl).host
  const pages = await (await fetch(`http://${debugHost}/json/list`)).json()
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl)
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }) })
  let commandId = 0
  const pending = new Map()
  const exceptions = []
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data)
    if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails)
    const callbacks = pending.get(message.id)
    if (callbacks) {
      pending.delete(message.id)
      if (message.error) callbacks.reject(new Error(message.error.message))
      else callbacks.resolve(message.result)
    }
  })
  const send = (method, params = {}) => new Promise((resolve, reject) => { const id = ++commandId; pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })) })
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    assert.ok(!result.exceptionDetails, JSON.stringify(result.exceptionDetails))
    return result.result.value
  }
  const waitFor = condition => evaluate(`new Promise((resolve, reject) => { const started = Date.now(); const check = () => { if (${condition}) resolve(true); else if (Date.now() - started > 5000) reject(new Error('Condition timed out')); else setTimeout(check, 20) }; check() })`)
  await send('Runtime.enable')
  await send('Page.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false })
  await send('Page.navigate', { url: `http://127.0.0.1:${server.address().port}` })
  await waitFor('typeof window.runSettingsChecks === "function"')
  assert.equal(await evaluate('window.runSettingsChecks()'), true)
  await waitFor('document.body.textContent.includes("Workspace breakdown")')
  await evaluate('[...document.querySelectorAll("h2")].find(heading => heading.textContent === "Storage & backup").scrollIntoView()')
  const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
  writeFileSync(resolve('node_modules/.cache/settings-browser.png'), Buffer.from(screenshot.data, 'base64'))
  assert.deepEqual(exceptions, [])
  console.log('PASS: browser profile/password forms, timezone preview, storage summary, backup/restore confirmation, lock-screen privacy and unlocking.')
} finally {
  socket?.close()
  processHandle.kill()
  if (processHandle.exitCode === null) await new Promise(resolve => processHandle.once('exit', resolve))
  await new Promise(resolve => server.close(resolve))
  const target = resolve(profile)
  assert.ok(target.startsWith(resolve(tmpdir()) + sep) && target.includes('factumdb-settings-browser-'))
  rmSync(target, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 })
}

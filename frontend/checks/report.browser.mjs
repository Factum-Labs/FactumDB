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
const bundled = await build({ entryPoints: ['checks/report.browser.tsx'], bundle: true, platform: 'browser', format: 'esm', jsx: 'automatic', write: false, define: { 'process.env.NODE_ENV': '"development"' } })
const fixturePdf = readFileSync(resolve('checks/fixtures/report-summary.pdf')).toString('base64')
const script = `window.reportPdfBase64 = ${JSON.stringify(fixturePdf)};\n` + bundled.outputFiles[0].text
const assets = resolve('dist/assets')
const css = readFileSync(join(assets, readdirSync(assets).find(name => name.endsWith('.css'))), 'utf8')
const securityPolicy = JSON.parse(readFileSync(resolve('../src-tauri/tauri.conf.json'), 'utf8')).app.security.csp
const server = createServer((request, response) => {
  response.setHeader('Content-Security-Policy', securityPolicy)
  if (request.url?.startsWith('/pdf-assets/')) {
    const file = resolve('dist', request.url.slice(1))
    if (!file.startsWith(resolve('dist/pdf-assets') + sep)) { response.writeHead(403).end(); return }
    response.setHeader('Content-Type', file.endsWith('.mjs') || file.endsWith('.js') ? 'application/javascript' : file.endsWith('.wasm') ? 'application/wasm' : 'application/octet-stream')
    response.end(readFileSync(file)); return
  }
  response.setHeader('Content-Type', (request.url === '/test.js' ? 'application/javascript' : request.url === '/style.css' ? 'text/css' : 'text/html') + '; charset=utf-8')
  response.end(request.url === '/test.js' ? script : request.url === '/style.css' ? css : `<!doctype html><link rel="stylesheet" href="/style.css"><div id="root"></div><script type="module" src="/test.js"></script>`)
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const profile = mkdtempSync(join(tmpdir(), 'factumdb-report-browser-'))
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
  const button = text => `Array.from(document.querySelectorAll('button')).find(button => button.textContent.trim() === ${JSON.stringify(text)})`
  const click = expression => evaluate(`(${expression}).click()`)
  await waitFor(`document.body.textContent.includes('Preview export')`)
  assert.equal(await evaluate(`(${button('Generate PDF report')}).disabled`), true)
  await waitFor(`document.body.textContent.includes('Grouped findings')`)
  assert.equal(await evaluate(`Array.from(document.querySelectorAll('button')).some(button => button.textContent.trim() === 'CSV')`), false)
  assert.equal(await evaluate(`document.querySelectorAll('input[type=checkbox]').length`), 0)
  await click(button('Preview export'))
  await waitFor(`document.querySelector('[data-testid=pdf-preview-canvas]')?.dataset.renderedPage === '1'`)
  const colors = await evaluate(`(() => { const canvas = document.querySelector('canvas'); const pixels = canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data; let colored=0; for(let i=0;i<pixels.length;i+=4) if(Math.max(...pixels.slice(i,i+3))-Math.min(...pixels.slice(i,i+3))>20) colored++; return colored })()`)
  assert.ok(colors > 100, 'PDF preview must contain rendered colored artwork.')
  const firstPageImage = await evaluate(`document.querySelector('canvas').toDataURL()`)
  assert.equal(await evaluate(`window.reportCalls.some(call => call.command === 'export_preview_status')`), true)
  await click(button('Next'))
  await waitFor(`document.querySelector('[data-testid=pdf-preview-canvas]')?.dataset.renderedPage === '2'`)
  await click(button('Previous'))
  await waitFor(`document.querySelector('[data-testid=pdf-preview-canvas]')?.dataset.renderedPage === '1'`)
  assert.equal(await evaluate(`document.querySelector('canvas').toDataURL()`), firstPageImage)
  await click(button('Choose destination'))
  await waitFor(`!(${button('Generate PDF report')}).disabled`)
  await click(button('Generate PDF report'))
  await waitFor(`window.reportCalls.some(call => call.command === 'export_case')`)
  const saved = await evaluate(`window.reportCalls.find(call => call.command === 'export_case').payload`)
  assert.equal(saved.redacted, true)
  assert.equal(saved.preview_token, 'preview-1')
  assert.equal(saved.format, 'PDF')
  assert.equal(saved.profile, undefined)
  assert.equal(saved.sections, undefined)
  await waitFor(`document.body.textContent.includes('Exported by Examiner')`)
  await click(button('JSON'))
  await waitFor(`document.body.textContent.includes('Generate JSON export')`)
  assert.equal(await evaluate(`document.querySelector('input[required]').value`), '')
  assert.equal(await evaluate(`(${button('Generate JSON export')}).disabled`), true)
  await evaluate('window.holdPreparation = true')
  await click(button('Preview export'))
  await waitFor(`document.body.textContent.includes('Preparing reconciliation')`)
  assert.equal(await evaluate(`document.querySelector('[role=progressbar]')?.getAttribute('aria-label')`), 'Report preparation')
  assert.equal(await evaluate(`document.querySelector('[role=progressbar]').hasAttribute('aria-valuenow')`), false, 'Unknown totals must not imply a percentage.')
  await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] })
  assert.equal(await evaluate(`getComputedStyle(document.querySelector('.report-preparation-activity')).animationName`), 'none')
  await send('Emulation.setEmulatedMedia', { features: [] })
  const loadingScreenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
  writeFileSync(resolve('node_modules/.cache/report-loading-browser.png'), Buffer.from(loadingScreenshot.data, 'base64'))
  await click(button('Cancel preparation'))
  await waitFor(`window.reportCalls.some(call => call.command === 'cancel_export_preview')`)
  assert.equal(await evaluate(`!!document.querySelector('[data-testid=export-preview-content]')`), false)
  await evaluate('window.holdPreparation = false')
  await click(button('Preview export'))
  await waitFor(`document.querySelector('[data-testid=export-preview-content]')`)
  assert.equal(await evaluate(`document.body.textContent.includes('Full case JSON')`), true)
  await evaluate(`const select = Array.from(document.querySelectorAll('select')).find(select => select.value === 'redacted'); select.value='full'; select.dispatchEvent(new Event('change',{bubbles:true}))`)
  await waitFor(`!document.querySelector('[data-testid=export-preview-content]')`)
  await click(button('PDF'))
  await click(button('Preview export'))
  await waitFor(`document.querySelector('[data-testid=pdf-preview-canvas]')?.dataset.renderedPage === '1'`)
  // Retain the finished PDF while JSON prepares, and restore JSON's live progress.
  const beforeSwitch = await evaluate(`window.reportCalls.filter(call => call.command === 'preview_export').length`)
  await click(button('JSON'))
  await evaluate('window.holdPreparation = true')
  await click(button('Preview export'))
  await waitFor(`document.body.textContent.includes('Preparing reconciliation')`)
  await click(button('PDF'))
  await waitFor(`document.querySelector('[data-testid=pdf-preview-canvas]')?.dataset.renderedPage === '1'`)
  await click(button('JSON'))
  await waitFor(`document.body.textContent.includes('Preparing reconciliation') && document.body.textContent.includes('Cancel preparation')`)
  assert.equal(await evaluate(`window.reportCalls.filter(call => call.command === 'preview_export').length`), beforeSwitch + 1, 'Switching back must resume the same JSON job.')
  await evaluate('window.holdPreparation = false')
  await waitFor(`document.querySelector('[data-testid=export-preview-content]')`)
  await click(button('PDF'))
  await waitFor(`document.querySelector('[data-testid=pdf-preview-canvas]')?.dataset.renderedPage === '1'`)
  assert.equal(await evaluate(`window.reportCalls.filter(call => call.command === 'preview_export').length`), beforeSwitch + 1, 'The completed PDF remains available without regeneration.')
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
  const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
  writeFileSync(resolve('node_modules/.cache/report-browser.png'), Buffer.from(screenshot.data, 'base64'))
  const manualPreviews = await evaluate(`window.reportCalls.filter(call => call.command === 'preview_export').length`)
  await evaluate(`const content = Array.from(document.querySelectorAll('select')).find(select => select.value === 'full'); content.value='redacted'; content.dispatchEvent(new Event('change',{bubbles:true})); window.startBackgroundReports()`)
  await waitFor(`window.reportCalls.some(call => call.command === 'claim_background_report' && call.payload.format === 'PDF') && document.querySelector('[data-testid=pdf-preview-canvas]')?.dataset.renderedPage === '1'`)
  await click(button('JSON'))
  await waitFor(`window.reportCalls.some(call => call.command === 'claim_background_report' && call.payload.format === 'JSON') && document.querySelector('[data-testid=export-preview-content]')`)
  await click(button('PDF'))
  await waitFor(`document.querySelector('[data-testid=pdf-preview-canvas]')?.dataset.renderedPage === '1'`)
  assert.equal(await evaluate(`window.reportCalls.filter(call => call.command === 'preview_export').length`), manualPreviews, 'Both warmed formats appear without manual preparation.')
  assert.deepEqual(exceptions, [])
  console.log('PASS: rendered colored PDF, paging, frozen preview export, full JSON manifest, cancellation, redaction invalidation, automatic warmed PDF/JSON previews, and CSV removal.')
} finally {
  socket?.close()
  processHandle.kill()
  if (processHandle.exitCode === null) await new Promise(resolve => processHandle.once('exit', resolve))
  await new Promise(resolve => server.close(resolve))
  const target = resolve(profile)
  assert.ok(target.startsWith(resolve(tmpdir()) + sep) && target.includes('factumdb-report-browser-'))
  rmSync(target, { recursive: true, force: true, maxRetries: 20, retryDelay: 200 })
}

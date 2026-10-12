import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve, sep } from 'node:path'
import { test } from 'node:test'
import { bundleReady, prepareDevRuntime } from './prepare_dev_runtime.mjs'

test('Windows development repairs partial bundles and leaves complete bundles alone', () => {
  const root = mkdtempSync(join(tmpdir(), 'factumdb-dev-runtime-'))
  const bundle = join(root, 'src-tauri/resources/runtime/windows')
  const lock = { target: 'test-windows', python: { sha256: 'pinned-python' }, vc_runtime: { files: {} } }
  const tools = { python_path: 'python/python.exe', innochecksum_path: 'mysql/innochecksum.exe', ibd2sdi_path: 'mysql/ibd2sdi.exe', mysqlbinlog_path: 'mysql/mysqlbinlog.exe', ibd2sql_path: 'ibd2sql/main.py' }
  const manifest = { target: lock.target, tools, artifacts: lock, files: Object.fromEntries([...Object.values(tools), 'mysql/runtime.dll', 'python-packages/factumdb-pdf.json'].map(path => [path, 'test-hash'])) }
  const install = () => {
    for (const path of Object.keys(manifest.files)) {
      mkdirSync(join(bundle, path, '..'), { recursive: true })
      writeFileSync(join(bundle, path), 'fixture')
    }
    writeFileSync(join(bundle, 'manifest.json'), JSON.stringify(manifest))
  }
  try {
    mkdirSync(join(root, 'scripts'), { recursive: true })
    writeFileSync(join(root, 'scripts/windows-bundle.lock.json'), JSON.stringify(lock))
    let calls = 0
    const run = (command, args, options) => {
      assert.equal(command, 'py')
      assert.deepEqual(args, ['-3', join(root, 'scripts/prepare_windows_bundle.py')])
      assert.equal(options.cwd, root)
      calls++; install(); return { status: 0 }
    }
    prepareDevRuntime({ platform: 'linux', root, run })
    assert.equal(calls, 0)
    assert.equal(bundleReady(bundle, lock), false)
    prepareDevRuntime({ platform: 'win32', root, run })
    assert.equal(calls, 1)
    assert.equal(bundleReady(bundle, lock), true)
    prepareDevRuntime({ platform: 'win32', root, run })
    assert.equal(calls, 1)
    // Simulate a stale manifest with a missing dependency, not just missing executables.
    rmSync(join(bundle, 'mysql/runtime.dll'))
    prepareDevRuntime({ platform: 'win32', root, run })
    assert.equal(calls, 2)
    assert.equal(bundleReady(bundle, { ...lock, python: { sha256: 'new-python' } }), false)
    writeFileSync(join(bundle, 'manifest.json'), '{broken')
    assert.equal(bundleReady(bundle, lock), false)
    assert.throws(() => prepareDevRuntime({ platform: 'win32', root, run: () => ({ status: 1 }) }), /preparation failed/)
    writeFileSync(join(bundle, 'manifest.json'), JSON.stringify({ ...manifest, tools: { ...tools, ibd2sql_path: '../../outside.py' } }))
    assert.equal(bundleReady(bundle, lock), false)
  } finally {
    const target = resolve(root)
    assert.ok(target.startsWith(resolve(tmpdir()) + sep) && target.includes('factumdb-dev-runtime-'))
    rmSync(target, { recursive: true, force: true })
  }
})

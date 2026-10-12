// Tauri's dev launcher needs the same pinned tool bundle as the Windows installer.
import { readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const required = ['python_path', 'innochecksum_path', 'ibd2sdi_path', 'mysqlbinlog_path', 'ibd2sql_path']

export function bundleReady(bundle, lock) {
  try {
    const manifest = JSON.parse(readFileSync(join(bundle, 'manifest.json'), 'utf8'))
    if (manifest.target !== lock.target) return false
    for (const [name, artifact] of Object.entries(lock)) {
      if (artifact && typeof artifact === 'object' && 'sha256' in artifact && manifest.artifacts?.[name]?.sha256 !== artifact.sha256) return false
    }
    if (JSON.stringify(manifest.artifacts?.vc_runtime) !== JSON.stringify(lock.vc_runtime)) return false
    const containedFile = value => {
      if (typeof value !== 'string' || !value) return false
      const target = resolve(bundle, value)
      const fromBundle = relative(resolve(bundle), target)
      return fromBundle !== '..' && !fromBundle.startsWith(`..${sep}`) && !fromBundle.includes(':') && statSync(target).isFile()
    }
    if (!containedFile("python-packages/factumdb-pdf.json")) return false
    if (!required.every(name => containedFile(manifest.tools?.[name]))) return false
    // A leftover Python directory alone, or a missing MySQL DLL, is not a complete bundle.
    return !!manifest.files && Object.keys(manifest.files).length > 0 && Object.keys(manifest.files).every(containedFile)
  } catch { return false }
}

export function prepareDevRuntime({ platform = process.platform, root = projectRoot, run = spawnSync } = {}) {
  if (platform !== 'win32') return
  const lock = JSON.parse(readFileSync(join(root, 'scripts/windows-bundle.lock.json'), 'utf8'))
  const bundle = join(root, 'src-tauri/resources/runtime/windows')
  if (bundleReady(bundle, lock)) return
  console.log('Windows dev runtime is missing or incomplete. Restoring pinned tools…')
  const result = run('py', ['-3', join(root, 'scripts/prepare_windows_bundle.py')], { cwd: root, stdio: 'inherit', windowsHide: true })
  if (result.error) throw result.error
  if (result.status !== 0) throw new Error(`Windows runtime preparation failed (exit ${result.status}). See the staging error above.`)
  if (!bundleReady(bundle, lock)) throw new Error('Runtime preparation did not produce a complete Windows tool bundle.')
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try { prepareDevRuntime() } catch (error) { console.error(error.message); process.exitCode = 1 }
}

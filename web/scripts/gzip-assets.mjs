// Post-build step: create .gz twins of the built text assets so the Pico can
// serve them with Content-Encoding: gzip (it can't compress at runtime).
// The original files are kept as a fallback for clients that don't accept gzip.

import { readdir, readFile, writeFile } from 'node:fs/promises'
import { gzipSync } from 'node:zlib'
import { join, resolve } from 'node:path'

// npm scripts run with cwd = web/, and the build output is ../www.
const ROOT = resolve(process.cwd(), '..', 'www')
const COMPRESS = ['.js', '.css', '.html', '.svg', '.json', '.map', '.ico']

async function walk(dir) {
  let saved = 0
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const p = join(dir, entry.name)
    if (entry.isDirectory()) {
      saved += await walk(p)
    } else if (
      COMPRESS.some((ext) => entry.name.endsWith(ext)) &&
      !entry.name.endsWith('.gz')
    ) {
      const buf = await readFile(p)
      const gz = gzipSync(buf, { level: 9 })
      if (gz.length < buf.length) {
        await writeFile(`${p}.gz`, gz)
        saved += buf.length - gz.length
      }
    }
  }
  return saved
}

const saved = await walk(ROOT)
console.log(`gzip: precompressed assets in www/ (saved ~${(saved / 1024).toFixed(1)} KB on the wire)`)

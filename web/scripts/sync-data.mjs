// Copies the root streams.json into public/ so the dev server serves fresh data.
// (runs automatically before npm run dev / build)
import { copyFile, mkdir } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '../../streams.json')
const dest = resolve(here, '../public/streams.json')

if (!existsSync(src)) {
  console.warn('../streams.json not found - run python3 src/build.py first')
  process.exit(0)
}
await mkdir(dirname(dest), { recursive: true })
await copyFile(src, dest)
console.log('✓ streams.json -> web/public/')

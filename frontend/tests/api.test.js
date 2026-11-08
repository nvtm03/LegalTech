import test from 'node:test'
import assert from 'node:assert/strict'
import { request } from '../src/analysis-state.js'

test('successful empty delete allows the caller to clear its state',async()=>{
  const original=globalThis.fetch
  globalThis.fetch=async()=>new Response(null,{status:204})
  try { assert.equal(await request('/api/analyses/example',{method:'DELETE'}),null) }
  finally {globalThis.fetch=original}
})

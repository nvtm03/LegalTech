import test from 'node:test'
import assert from 'node:assert/strict'
import { sameInput, decodeText } from '../src/analysis-state.js'

test('a result cannot belong to changed text, type, model or provider',()=>{
  const input={text:'Документ A',doc_type:'terms',model:'model-a',provider:'router'}
  assert.equal(sameInput(input,{...input}),true)
  for(const [key,value] of [['text','Документ B'],['doc_type','privacy'],['model','model-b'],['provider','google']]){
    assert.equal(sameInput(input,{...input,[key]:value}),false)
  }
  assert.equal(sameInput(null,input),false)
})

test('invalid UTF-8 is rejected instead of replacing document characters',()=>{
  assert.equal(decodeText(new TextEncoder().encode('Договор')), 'Договор')
  assert.throws(()=>decodeText(new Uint8Array([0xc4,0xee,0xe3,0xee,0xe2,0xee,0xf0])))
})

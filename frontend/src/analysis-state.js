export function sameInput(snapshot, draft) {
  return Boolean(snapshot) && ['text','doc_type','model','provider'].every(key=>snapshot[key]===draft[key])
}

export function decodeText(bytes) {
  return new TextDecoder('utf-8',{fatal:true}).decode(bytes)
}

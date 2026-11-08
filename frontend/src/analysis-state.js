export function sameInput(snapshot, draft) {
  return Boolean(snapshot) && ['text','doc_type','model','provider'].every(key=>snapshot[key]===draft[key])
}

export function decodeText(bytes) {
  return new TextDecoder('utf-8',{fatal:true}).decode(bytes)
}

export async function request(url, options) {
  const response = await fetch(url, options)
  if (response.status === 204 && response.ok) return null
  const data = await response.json()
  if (!response.ok) {const e=new Error(typeof data.detail === 'string' ? data.detail : 'Проверьте текст и настройки запроса.'); e.status=response.status; throw e}
  return data
}

import QRCode from 'qrcode'

/** QR как картинка data:image/svg+xml — векторный, чёткий при печати, без вставки разметки в страницу. */
export async function qrDataUrl(text: string): Promise<string> {
  const svg = await QRCode.toString(text, { type: 'svg', margin: 0, errorCorrectionLevel: 'M' })
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}

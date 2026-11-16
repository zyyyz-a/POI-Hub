// All processing stays in the browser. Nothing goes to a third-party image service.
export const WECHAT_IMAGE_BYTES = 5 * 1024 * 1024
export const MAX_SOURCE_PHOTO_BYTES = 20 * 1024 * 1024

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('照片无法读取。请在手机或图片软件中导出为JPG/PNG后重试；只修改后缀无效。HEIC/HEIF需浏览器支持。'))
    image.src = url
  })
}

function encode(canvas: HTMLCanvasElement, type: 'image/jpeg' | 'image/png', quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) resolve(blob)
      else reject(new Error('当前浏览器无法处理照片，请换一张照片或使用新版浏览器。'))
    }, type, quality)
  })
}

// Read the actual file signature: a .jpg picked from WeChat may really be WebP.
async function bytes(blob: Blob): Promise<Uint8Array> {
  if (typeof blob.arrayBuffer === 'function') return new Uint8Array(await blob.arrayBuffer())
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer))
    reader.onerror = () => reject(new Error('照片文件读取失败，请重新选择。'))
    reader.readAsArrayBuffer(blob)
  })
}

async function actualType(file: File): Promise<string> {
  const header = await bytes(file.slice(0, 32))
  const ascii = (start: number, length: number) => String.fromCharCode(...header.slice(start, start + length))
  if (header[0] === 0xff && header[1] === 0xd8 && header[2] === 0xff) return 'image/jpeg'
  if ([137, 80, 78, 71, 13, 10, 26, 10].every((value, i) => header[i] === value)) return 'image/png'
  if (ascii(0, 2) === 'BM') return 'image/bmp'
  if (ascii(0, 4) === 'RIFF' && ascii(8, 4) === 'WEBP') return 'image/webp'
  if (ascii(4, 4) === 'ftyp') {
    const brand = ascii(8, 4)
    if (['avif', 'avis'].includes(brand)) return 'image/avif'
    if (['heic', 'heix', 'hevc', 'hevx', 'mif1', 'msf1'].includes(brand)) return 'image/heic'
  }
  throw new Error('文件内容不是可识别的照片。请选择原始图片或导出JPG/PNG；不支持PDF、SVG或视频。')
}

export async function prepareApplymentPhoto(file: File, limit = WECHAT_IMAGE_BYTES): Promise<{ file: File; compressed: boolean; converted: boolean }> {
  if (!file.size) throw new Error('请选择非空的照片。')
  if (file.size > MAX_SOURCE_PHOTO_BYTES) throw new Error('原照片超过20MB，请选择普通手机照片或先裁去无关背景。')
  const maximum = Math.min(WECHAT_IMAGE_BYTES, limit)
  if (!Number.isFinite(maximum) || maximum < 1024) throw new Error('图片上传配置异常，请刷新页面后重试。')
  const type = await actualType(file)
  // Use the detected MIME for decoding too; never trust a misleading filename/type.
  const url = URL.createObjectURL(file.slice(0, file.size, type))
  const canvas = document.createElement('canvas')
  try {
    const image = await loadImage(url)
    const width = image.naturalWidth
    const height = image.naturalHeight
    if (!width || !height || width * height > 64_000_000) throw new Error('照片分辨率过大，请先裁去无关背景后重试。')
    const tail = type === 'image/jpeg' ? await bytes(file.slice(-2)) : null
    const canonical = ['image/png', 'image/bmp'].includes(type) || (tail?.[0] === 0xff && tail?.[1] === 0xd9)
    if (canonical && file.size <= maximum) {
      const sameMime = file.type === type
      const extension = type === 'image/jpeg' ? 'jpg' : type === 'image/png' ? 'png' : 'bmp'
      return { file: sameMime ? file : new File([file], `merchant-photo.${extension}`, { type, lastModified: file.lastModified }), compressed: false, converted: !sameMime }
    }
    const context = canvas.getContext('2d')
    if (!context) throw new Error('浏览器不支持照片处理，请换用新版浏览器。')
    const longest = Math.max(width, height)
    let edge = Math.min(longest, 4096)
    const minimum = Math.min(longest, 1600)
    while (true) {
      canvas.width = Math.max(1, Math.round(width * edge / longest))
      canvas.height = Math.max(1, Math.round(height * edge / longest))
      // Flatten transparent images against white; never crop or stretch documents.
      context.fillStyle = '#ffffff'
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.drawImage(image, 0, 0, canvas.width, canvas.height)
      // For a small mislabelled photo or JPEG with trailing bytes, prefer lossless
      // decoded pixels in PNG. No extension-only "conversion" and no server bypass.
      if (file.size <= maximum && edge === longest) {
        const png = await encode(canvas, 'image/png')
        if (png.size <= maximum) return { file: new File([png], 'merchant-photo.png', { type: 'image/png', lastModified: file.lastModified }), compressed: false, converted: true }
      }
      for (const quality of [0.94, 0.86, 0.78, 0.72]) {
        const blob = await encode(canvas, 'image/jpeg', quality)
        if (blob.size <= maximum) {
          return { file: new File([blob], 'merchant-photo.jpg', { type: 'image/jpeg', lastModified: file.lastModified }), compressed: true, converted: type !== 'image/jpeg' || !canonical }
        }
      }
      if (edge <= minimum) break
      edge = Math.max(minimum, Math.floor(edge * 0.8))
    }
    throw new Error('照片仍过大，为避免证件文字模糊，请裁去背景或重新拍摄后上传。')
  } finally {
    URL.revokeObjectURL(url)
    canvas.width = 0
    canvas.height = 0
  }
}

import { afterEach, describe, expect, it, vi } from 'vitest'
import { prepareApplymentPhoto, WECHAT_IMAGE_BYTES, MAX_SOURCE_PHOTO_BYTES } from '../src/common/applymentPhoto'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

function photo(size: number, type = 'image/jpeg', actual = type) {
  const data = new Uint8Array(size)
  if (actual === 'image/jpeg') { data.set([255, 216, 255]); data.set([255, 217], size - 2) }
  else if (actual === 'image/png') data.set([137, 80, 78, 71, 13, 10, 26, 10])
  else if (actual === 'image/webp') data.set([82, 73, 70, 70, 0, 0, 0, 0, 87, 69, 66, 80])
  return new File([data], 'private-original.jpg', { type })
}

function imageMocks(fail = false) {
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:local-processing-only')
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  class FakeImage {
    naturalWidth = 6000
    naturalHeight = 4000
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    set src(_url: string) { queueMicrotask(() => fail ? this.onerror?.() : this.onload?.()) }
  }
  vi.stubGlobal('Image', FakeImage)
  const context = { fillStyle: '', fillRect: vi.fn(), drawImage: vi.fn() }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
  return { revoke, context }
}

describe('private local photo preparation', () => {
  it('keeps a valid three-megabyte photo unchanged', async () => {
    imageMocks()
    const source = photo(3 * 1024 * 1024)
    expect(await prepareApplymentPhoto(source)).toEqual({ file: source, compressed: false, converted: false })
  })

  it('accepts the exact five-megabyte boundary without lossy conversion', async () => {
    imageMocks()
    const source = photo(WECHAT_IMAGE_BYTES)
    expect((await prepareApplymentPhoto(source)).file).toBe(source)
  })

  it('compresses a phone photo locally and does not modify the original', async () => {
    const { revoke, context } = imageMocks()
    const encode = vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(callback => callback(new Blob([new Uint8Array(1024)], { type: 'image/jpeg' })))
    const source = photo(8 * 1024 * 1024)
    const result = await prepareApplymentPhoto(source)
    expect(result.compressed).toBe(true)
    expect(result.file.type).toBe('image/jpeg')
    expect(result.file.size).toBeLessThanOrEqual(WECHAT_IMAGE_BYTES)
    expect(result.file.name).toBe('merchant-photo.jpg')
    expect(source.size).toBe(8 * 1024 * 1024)
    expect(source.name).toBe('private-original.jpg')
    expect(context.drawImage).toHaveBeenCalled()
    expect(encode).toHaveBeenCalled()
    expect(revoke).toHaveBeenCalledWith('blob:local-processing-only')
  })

  it('tries a lower JPEG quality if the first encoding is still too large', async () => {
    imageMocks()
    const tooLarge = new Blob([new Uint8Array(WECHAT_IMAGE_BYTES + 1)], { type: 'image/jpeg' })
    const small = new Blob([new Uint8Array(1024)], { type: 'image/jpeg' })
    const encode = vi.spyOn(HTMLCanvasElement.prototype, 'toBlob')
      .mockImplementationOnce(callback => callback(tooLarge))
      .mockImplementation(callback => callback(small))
    expect((await prepareApplymentPhoto(photo(6 * 1024 * 1024))).compressed).toBe(true)
    expect(encode.mock.calls.map(call => call[2])).toEqual([0.94, 0.86])
  })

  it('cleans up a corrupt source without sending it anywhere', async () => {
    const { revoke } = imageMocks(true)
    await expect(prepareApplymentPhoto(photo(6 * 1024 * 1024))).rejects.toThrow('照片无法读取')
    expect(revoke).toHaveBeenCalled()
  })

  it('rejects unsupported formats and unreasonable source sizes', async () => {
    await expect(prepareApplymentPhoto(photo(1024, 'application/pdf'))).rejects.toThrow('不支持PDF')
    await expect(prepareApplymentPhoto(photo(MAX_SOURCE_PHOTO_BYTES + 1))).rejects.toThrow('原照片超过20MB')
  })

  it('converts a small WebP disguised as a JPEG instead of sending it raw', async () => {
    imageMocks()
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(callback => callback(new Blob([new Uint8Array(1024)], { type: 'image/jpeg' })))
    const source = photo(2048, 'image/jpeg', 'image/webp')
    const result = await prepareApplymentPhoto(source)
    expect(result.converted).toBe(true)
    expect(result.file.type).toBe('image/jpeg')
    expect(result.file).not.toBe(source)
    expect(source.type).toBe('image/jpeg')
  })

  it('repairs an incorrect MIME without recompressing valid PNG pixels', async () => {
    const { context } = imageMocks()
    const source = photo(2048, 'application/octet-stream', 'image/png')
    const result = await prepareApplymentPhoto(source)
    expect(result.file.type).toBe('image/png')
    expect(result.converted).toBe(true)
    expect(result.compressed).toBe(false)
    expect(context.drawImage).not.toHaveBeenCalled()
  })

  it('decodes small files too and rejects a broken image before upload', async () => {
    const { revoke } = imageMocks(true)
    await expect(prepareApplymentPhoto(photo(1024))).rejects.toThrow('照片无法读取')
    expect(revoke).toHaveBeenCalled()
  })

  it('rejects SVG content renamed to jpg rather than merely trusting MIME', async () => {
    const source = new File(['<svg xmlns="http://www.w3.org/2000/svg"></svg>'], 'fake.jpg', { type: 'image/jpeg' })
    await expect(prepareApplymentPhoto(source)).rejects.toThrow('不支持PDF、SVG或视频')
  })

  it('normalizes a JPEG with trailing bytes instead of triggering server rejection', async () => {
    imageMocks()
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(callback => callback(new Blob([new Uint8Array(1024)], { type: 'image/jpeg' })))
    const source = new File([photo(2048), '\nextra-metadata'], 'phone.jpg', { type: 'image/jpeg' })
    const result = await prepareApplymentPhoto(source)
    expect(result.converted).toBe(true)
    expect(result.file).not.toBe(source)
  })
})

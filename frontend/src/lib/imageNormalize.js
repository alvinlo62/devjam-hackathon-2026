// 後端 ai/client.py 送圖給 Gemini 時 mime type 是寫死 image/jpeg（見該檔案
// _image_part()），所以無論民眾選了什麼格式的照片，都要在前端先轉成真的
// JPEG bytes，兩邊才會一致——不然 PNG/WebP/HEIC 等格式送過去會被誤判成
// JPEG 而解碼失敗。已經是 JPEG 的檔案不重複轉檔，省一次畫布往返。
export async function normalizeToJpeg(file) {
  if (file.type === 'image/jpeg' || file.type === 'image/jpg') return file

  const isHeic = /\.hei[cf]$/i.test(file.name) || /^image\/hei[cf]/i.test(file.type)
  if (isHeic) {
    // HEIC/HEIF（iPhone 預設格式）瀏覽器原生無法解碼，連畫到 canvas 都不行，
    // 要靠 heic2any 這個 WASM 轉檔庫先轉出真的 JPEG bytes。
    const heic2any = (await import('heic2any')).default
    const converted = await heic2any({ blob: file, toType: 'image/jpeg', quality: 0.9 })
    return new File([converted], file.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg' })
  }

  // 其餘瀏覽器原生可解碼的格式（PNG/WebP/GIF/BMP/AVIF...）：畫到 canvas
  // 再輸出成 JPEG，統一格式。
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = URL.createObjectURL(file)
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = img.naturalWidth
      canvas.height = img.naturalHeight
      const ctx = canvas.getContext('2d')
      ctx.drawImage(img, 0, 0)
      canvas.toBlob(
        (blob) => {
          URL.revokeObjectURL(url)
          if (!blob) {
            reject(new Error('圖片轉檔失敗，請換一張照片'))
            return
          }
          resolve(new File([blob], file.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg' }))
        },
        'image/jpeg',
        0.9,
      )
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('無法讀取這張圖片，請改用 JPG/PNG/WebP/HEIC 等常見圖片格式'))
    }
    img.src = url
  })
}

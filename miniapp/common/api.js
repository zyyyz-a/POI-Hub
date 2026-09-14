let config
try {
  config = require('../config')
} catch (error) {
  config = require('../config.example')
}

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    const token = getApp && getApp().globalData.accessToken
    wx.request({
      url: `${config.apiBaseUrl}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: response => {
        if (response.statusCode >= 200 && response.statusCode < 300) resolve(response.data)
        else reject(new Error(response.data?.detail?.message || response.data?.message || '请求失败'))
      },
      fail: reject
    })
  })
}

const root = `/public/mini-programs/${config.miniProgramId}`

module.exports = {
  miniProgramId: config.miniProgramId,
  login: code => request(`${root}/login`, { method: 'POST', data: { code } }),
  products: () => request(`${root}/products`),
  createOrder: data => request(`${root}/orders`, { method: 'POST', data }),
  getOrder: orderId => request(`${root}/orders/${orderId}`),
  pay: orderId => request(`${root}/orders/${orderId}/pay`, { method: 'POST', data: {} }),
  voucher: orderId => request(`${root}/orders/${orderId}/voucher`),
  appoint: (orderId, data) => request(`${root}/orders/${orderId}/appointment`, { method: 'POST', data })
}

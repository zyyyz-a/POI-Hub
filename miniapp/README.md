# 统一平台顾客小程序

这是“一个平台小程序服务多家商户”的顾客端，可导入微信开发者工具。门店由入口参数
（腾讯地图挂载路径的 `store_code` 或小程序码/分享卡片的 `scene`）动态解析，不写死
在安装包里。

上线前复制 `config.example.js` 为 `config.js`，填写 HTTPS API 域名和客服电话。
不要把 AppSecret、商户私钥、APIv3 密钥放进小程序代码。

## 页面结构

- `pages/store`：门店首页（门店信息 + 在售套餐 + 停业/空/失败状态）。
- `pages/product`：套餐详情与购买规则。
- `pages/order-confirm`：确认订单（数量固定为 1）。
- `pages/pay-result`：支付结果（以服务端订单状态为准，轮询确认）。
- `pages/orders`：订单列表（全部/待付款/待使用/已完成退款）。
- `pages/order-detail`：订单详情与继续支付/退款入口。
- `pages/appointment`：预约到店时间。
- `pages/voucher`：券码详情。
- `pages/refund`：退款申请。
- `pages/profile`：我的（订单、客服、协议、隐私、注销）。
- `pages/entry-error`：入口失效/门店不可用。

公共层：`common/api.js`（公开接口）、`common/entry.js`（入口解析）、
`common/util.js`（金额/时间/状态/幂等键）、`components/page-state`（加载/失败/空/停业）。

## 安全边界

- 收款商户号完全由服务端根据门店决定，小程序不传递也不展示。
- 支付成功以前端展示为准不算数，必须以服务端订单状态为准。
- 技术错误码不直接展示给顾客，只展示中文说明和客服入口。

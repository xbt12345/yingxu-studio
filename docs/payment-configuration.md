# 充值渠道配置

网站先保存充值订单的金额、币种、积分和收款方式。支付宝、微信只有在商户配置齐全时才提供自动收款；配置缺失时渠道关闭，可使用联系管理员入口。以下字段全部为配置名称，不包含真实凭据。

自动入账依据是支付平台通知，而不是浏览器的“支付成功”、跳转参数或用户上传的付款截图。`PaymentGateway` 只产生验签后的支付证据，账户账本再次核对持久订单，并用 `(provider, transaction_id)` 唯一约束防止重复入账。通知重复投递要返回成功应答，不重复增加积分。

## 支付宝

需开通支持 `alipay.trade.precreate` 的商户应用。设置：

| 环境变量 | 内容 |
| --- | --- |
| `YINGXU_ALIPAY_APP_ID` | 支付宝商户应用 ID |
| `YINGXU_ALIPAY_SELLER_ID` | 收款支付宝用户 ID |
| `YINGXU_ALIPAY_PRIVATE_KEY_PATH` | 商户 RSA 私钥 PEM 文件的绝对路径 |
| `YINGXU_ALIPAY_PUBLIC_KEY_PATH` | 支付宝 RSA 验签公钥 PEM 文件的绝对路径 |
| `YINGXU_ALIPAY_NOTIFY_URL` | 当前服务实际支付宝通知路由的公网 HTTPS URL |

如密钥由部署平台注入，也可使用对应的 `..._PEM` 变量代替 `..._PATH`。公钥必须来自商户平台，不能使用通知报文里的公钥。只接受 RSA2、UTF-8 签名。检查应用 ID、收款账号、商户订单号、人民币金额和成功状态后，再进入账本。

通知是 `application/x-www-form-urlencoded`，保留原始字段并拒绝重复字段。异步通知验签排除 `sign` 和 `sign_type`，排序其余非空字段；创建请求签名包含 `sign_type`。支付宝下单响应验证原始嵌套 JSON 的签名，不能先解析再重新格式化后验签。

## 微信支付

当前支持直连商户 APIv3 Native 扫码支付，不接受服务商、合单支付通知。

| 环境变量 | 内容 |
| --- | --- |
| `YINGXU_WECHAT_APP_ID` | 商户绑定的 AppID |
| `YINGXU_WECHAT_MCH_ID` | 直连商户号 |
| `YINGXU_WECHAT_MERCHANT_SERIAL` | 商户签名证书序列号 |
| `YINGXU_WECHAT_PRIVATE_KEY_PATH` | 商户 RSA 私钥 PEM 文件的绝对路径 |
| `YINGXU_WECHAT_PLATFORM_SERIAL` | 微信支付公钥 ID 或平台证书序列号 |
| `YINGXU_WECHAT_PLATFORM_PUBLIC_KEY_PATH` | 微信支付公钥或平台证书 PEM 文件的绝对路径 |
| `YINGXU_WECHAT_API_V3_KEY` | 商户平台设置的 32 字节 APIv3 密钥 |
| `YINGXU_WECHAT_NOTIFY_URL` | 当前服务实际微信通知路由的公网 HTTPS URL |

RSA 文件也可使用对应 `..._PEM` 环境变量。验签公钥标识必须与可信配置一致；证书/公钥轮换时由管理员更新配置，系统不会信任回调里临时提供的公钥。

先用 HTTP 头里的时间戳、随机串和**原始请求体字节**进行 RSA-SHA256 验签，再用 APIv3 密钥 AES-256-GCM 解密 `resource`。校验 `appid`、`mchid`、`out_trade_no`、`amount.total`（分）、`currency=CNY` 和 `trade_state=SUCCESS`。签名时间允许与服务端相差 300 秒，服务器需保持时钟准确。

## 银行卡与人工联系

银行卡只能作为人工转账渠道，不能凭用户点击“我已付款”自动入账。需配置：

| 环境变量 | 内容 |
| --- | --- |
| `YINGXU_BANK_ACCOUNT_NAME` | 收款户名 |
| `YINGXU_BANK_ACCOUNT_NUMBER` | 收款账号 |
| `YINGXU_BANK_NAME` | 开户银行 |
| `YINGXU_RECHARGE_CONTACT` | 管理员联系说明，可选 |

上述银行卡配置缺失时关闭银行卡入口。管理员必须在银行流水中核对真实到账、订单号与金额后，通过受管理员权限保护的确认接口入账。已经服务端发起自动支付的订单，不允许再走人工确认，避免自动通知与人工操作竞态。

## 接口与上线验证

- `PaymentGateway.methods()`：渠道状态，不返回商户密钥。
- `create_checkout(order)`：订单包含 `id`、`method`、`amount_minor`、`currency`；自动收款返回 `qr_code`、`checkout_reference`、`expires_at`（毫秒）。人工渠道返回说明，不返回已付款状态。
- `verify_alipay(form, order=None)` / `verify_wechat(headers, raw_body, order=None)`：返回 `provider`、`id`、`amount_minor`、`currency`、`transaction_id`。未传 `order` 时，调用方必须先获取持久订单并通过账本核对其冻结快照，不能直接增加余额。
- 支付请求前先持久化已发起自动收款的标记，防止回调先到或连接超时后与人工确认竞态。下单超时是“尚未确认”，重试须使用原订单；已标记的自动收款订单不走人工到账。

本地 `127.0.0.1` 无法接收支付平台的公网通知。正式启用前需真实商户资质、商户密钥、HTTPS 通知入口，以及小额支付、重复通知、错金额拒绝、到账与对账的实测。本次离线测试只使用临时生成的 RSA 密钥和模拟响应，不代表真实商户支付验收通过。

依赖：`cryptography`、本地二维码编码 `qrcode[pil]`，以及项目原有的 `requests`。二维码由支付平台真实返回的地址在本地编码，不调用外部二维码服务。

依据：[支付宝官方 Python SDK 签名实现](https://github.com/alipay/alipay-sdk-python-all/blob/master/alipay/aop/api/util/SignatureUtils.py)、[微信支付官方 Native 下单](https://pay.wechatpay.cn/doc/v3/merchant/4012791877)、[微信支付官方 SDK 通知验签与解密](https://github.com/wechatpay-apiv3/wechatpay-php/blob/main/README.md)。

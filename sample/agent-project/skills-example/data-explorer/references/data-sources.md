# 数据来源与字段说明

## 数据库表
| 表名 | 说明 | 主要字段 |
|---|---|---|
| `orders` | 订单表 | order_id, user_id, amount, status, created_at |
| `users` | 用户表 | user_id, name, email, registered_at |
| `products` | 商品表 | product_id, name, price, category |

## API 端点
| 端点 | 说明 | 认证方式 |
|---|---|---|
| `/api/v1/orders` | 查询订单 | Bearer Token |
| `/api/v1/users/profile` | 用户画像 | API Key |
| `/graphql` | GraphQL 统一接口 | Bearer Token |

## 数据文件
- Excel 报表路径：`/data/reports/`
- JSON 日志路径：`/data/logs/`

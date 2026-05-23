# 命名规范规则

## 变量与函数
- 小写 + 下划线：`get_user_name`, `total_count`
- 函数名以动词开头：`get_`, `set_`, `create_`, `delete_`
- 布尔变量用 is/has/should 前缀：`is_valid`, `has_permission`

## 类名
- 大驼峰：`UserService`, `OrderController`
- 异常类以 Error 结尾：`ConnectionError`

## 常量
- 全大写 + 下划线：`MAX_RETRIES`, `DEFAULT_TIMEOUT`
- 模块级常量放在文件顶部

## 私有成员
- 单下划线开头：`_internal_cache`
- 双下划线避免命名冲突：`__private`

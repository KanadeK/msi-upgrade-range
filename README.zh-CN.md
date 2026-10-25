# msi-upgrade-range

在执行安装之前，检查新版 MSI 的 Upgrade 表是否覆盖指定旧版安装包。
适用于 Windows 安装包维护者：定位版本上下界、第四段版本号、语言过滤、
OnlyDetect 和升级动作配置造成的升级识别问题。

要求 Python 3.11+，运行时无第三方依赖。读取 MSI 需要 Windows；
导出的 JSON 可在 Windows、Linux、macOS 比较。

~~~powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install .
.venv/Scripts/msi-upgrade-range.exe check --old old.msi --new new.msi --json
.venv/Scripts/msi-upgrade-range.exe export new.msi -o new.metadata.json
~~~

在项目目录运行可复现示例：

~~~sh
python -m msi_upgrade_range check --old examples/old.json --new examples/new.json --json
python examples/demo.py
~~~

退出码：0 表示有限静态检查通过；1 表示存在需审查的问题；2 表示输入错误或检查不完整。
示例先验证正确升级范围，再制造排除旧版的上界错误并确认检查失败。

此工具仅读取安装包数据库，不安装软件，不运行自定义操作，不调用 msiexec。
它不证明升级执行成功，也不替代 WiX/ICE 验证和虚拟机中的实际升级测试。
转换文件、运行时属性覆盖、注册表状态、组件规则、完整执行顺序等不在检查范围内。
条件表达式和动态卸载特性列表会明确提示审查。

导出文件不会覆盖已有文件，可能包含产品标识与条件文本，分享前请检查。
卸载：虚拟环境中的 python -m pip uninstall msi-upgrade-range。
工具没有缓存或后台服务；导出 JSON 可自行删除。
详细边界、输入限制和开发测试见 [英文文档](README.md)。


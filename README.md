# 比较基因组分析（CGAT）1.0.3

Windows 桌面程序，提供 WGDI 全流程分析和独立 Circos 绘图。默认打开 WGDI 全流程分析。

## 运行

双击 `dist/比较基因组分析/比较基因组分析.exe`。分发时需要保留同目录的 `_internal/`、`runtime/` 和 `bin/`。

开发运行：`run.cmd` 或 `.venv/Scripts/python.exe -m app`。

## 分析流程

1. 选择自动解析（基因组 FASTA + GFF3/GTF）或手动上传（FAI/长度表 + 注释 + 蛋白，CDS 可选）。
2. 选择自比较或跨物种，设置物种名称、过滤条件及项目位置。
3. 分步运行，或连续运行：预处理 → DIAMOND/BLASTP（也可导入完整 12 列 outfmt 6）→ 点阵图 → 共线性 → Ks → 块汇总 → Ks 图 → Circos。
4. 使用“打开已有项目”选择包含 `project.json` 的目录，恢复设置并续跑。
5. 选择“仅绘图”，可单独载入 WGDI GFF、长度和块信息表，调整样式并导出。

项目的 `prepared/` 保存预处理数据，`work/` 保存分析和缓存，`logs/` 保存日志，`results/` 保存导出结果。重跑前被替代的生成文件保存在 `history/`。输入和参数改变会使相关结果失效，不能直接复用旧结果。旧版未保存验证记录的项目会保守地要求重新运行。

每物种选择一个编码转录本，蛋白与 CDS 使用相同基因 ID。跨物种 Ks 合并输入时要求不同物种的基因 ID 唯一。手动输入同一基因多个转录本会给出错误提示。

本机线程数与 WGDI process 为 1–8。Ks 使用可用的 MUSCLE 或 MAFFT、Perl、pal2nal、PAML；工具缺失会给出提示。MAFFT 必须通过启动版本检查才可选择。

## 验证和修复说明

[1.0.3 修复说明](docs/修复说明_1.0.3.md)包含业务逻辑修复对应表、结果有效性判据及验证范围。

可移植测试：

```bat
.venv\Scripts\python.exe tests\test_core.py
.venv\Scripts\python.exe tests\test_prep.py
.venv\Scripts\python.exe tests\test_fai.py
.venv\Scripts\python.exe tests\test_blast_direction.py
.venv\Scripts\python.exe tests\test_logic_103.py
runtime\Scripts\python.exe tests\test_wgdi_compat.py
```

最后一组需要 WGDI 运行时。测试使用少量合成数据，生成文件保存在项目的构建测试目录；不依赖作者的科研数据。

## 打包

```bat
build\build.cmd
```

使用 PyInstaller 生成 one-folder 程序，并附加 `runtime/` 和 `bin/`。构建规格会隔离宿主 PATH 中无关的 DLL，避免与 Qt 的依赖冲突。WGDI 兼容适配脚本随程序打包，不修改系统安装的 WGDI。

已在本机 Windows 11 验证；其他系统尚未验证。

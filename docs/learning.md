# 话术记忆审核

异常提交只会生成待审候选。候选不改变回答。只有管理员令牌能批准、拒绝、停用或回滚。通话口令不能审核。

令牌放在环境变量 `ZHIYU_ADMIN_TOKEN`，不要写进命令参数。目录默认是 `var/learning`，可用 `ZHIYU_LEARNING_DIR` 改。

```bash
export ZHIYU_ADMIN_TOKEN='至少十六位且与提交令牌不同'
python -m zhiyu.learning.cli list
python -m zhiyu.learning.cli approve <id> --speak '因为资质上传有误。您还有不清楚的吗？'
python -m zhiyu.learning.cli disable <id>
python -m zhiyu.learning.cli rollback <id>
python -m zhiyu.learning.cli reject <id>
```

批准后的句子只对同一场景行、意图 `why` 生效。换一条场景不会用到它。停用或回滚后恢复原表解释。待审记录、图片和反馈里的指令都不会改提示词。

商家重复说不明白时，本地会多写一条 `followup`。它不是已批准话术，也没有外呼派单。写盘失败时，对客不说已经记下。

`/rsi` 只读展示这条链路：异常反馈、人工试听记录、候选改进、审核后生效、停用或回滚。数量来自本机已有文件。待审和未启用不算进化成果。这不是基础模型自训练，页面也不画提升曲线。不登录只能看数量。明细沿用管理员令牌，通话口令不能看。页面没有批准按钮。明细不返回原文、手机号、图片和会话编号。

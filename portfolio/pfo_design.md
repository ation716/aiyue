ask: 
先这样建立模型：
1. 选几个 symbol 买入和怎么分配仓位是没有关系的
2. 选几个受到风险和收益同时影响，也和资金体量有关，也和市场有关，短线情绪有关，选股策略有关
3. 怎么分配仓位也与风险和预期收益有关，也和当前仓位有关


为了快速验证其他模块，我最终设计成 3 个接口，
stock_keep 持股数量，接受 kwargs，这个根据交易策略，总持仓为 8，如果还有持仓股，需要用 8-持仓股；
position_managent 仓位管理，接受 kwargs，返回所有仓位可用仓位均可买入，根据可用仓位，对于传入的 symbol_list, 选出 stock_keep 返回的持股数量，然后再均分剩余仓位
ultimate_distribute 最终分配，依次调用 stock_keep 和 position_managent 返回结果
返回结果

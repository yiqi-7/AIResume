const modelErrors:Record<string,string> = {
  MODEL_NOT_CONFIGURED:'默认模型暂不可用，请稍后重试或使用自己的 API。',
  MODEL_KEY_REQUIRED:'请在模型设置中填写 API Key。',
  MODEL_NAME_REQUIRED:'请在模型设置中选择或填写模型名称。',
  MODEL_CLIENT_RESTRICTED:'当前服务不支持本网站调用，请更换模型服务。',
  MODEL_KEY_INVALID:'模型 Key 无效，请在模型设置中核对 Key 和对应服务。',
  MODEL_ACCESS_DENIED:'模型服务拒绝访问，请检查 Key 权限或更换服务。',
  MODEL_REQUEST_REJECTED:'请求未被接受，请检查 API 地址、模型名称和高级设置中的协议。',
  MODEL_RATE_LIMITED:'模型服务额度不足或请求过于频繁，请检查余额或稍后再试。',
  MODEL_UPSTREAM:'模型服务暂时没有返回结果，请稍后重试或切换模型。',
  MODEL_INVALID_OUTPUT:'暂时无法生成可用的修改建议，请重试或切换模型。',
  MODEL_TIMEOUT:'模型调用超时，请稍后重试或切换响应更快的模型。',
  MODEL_OUTPUT_LIMIT:'模型回复不完整，请重试或切换模型。',
  MODEL_URL_UNREACHABLE:'API 地址无法连接到公网服务，请检查地址与服务状态。',
  MODEL_URL_INVALID:'请填写有效的公网 HTTPS API 地址。',
  TOKEN_BUDGET:'默认模型今日额度已用完，可以在模型设置中使用自己的 API。',
};

export function modelErrorMessage(code:string|null):string {
  return modelErrors[code??'']??'本次分析未完成，请检查模型设置或稍后重试。';
}

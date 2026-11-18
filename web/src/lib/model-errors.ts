const modelErrors:Record<string,string> = {
  MODEL_CLIENT_RESTRICTED:'当前接口仅允许 Coding 客户端，拒绝网页应用调用。请切换允许普通 API 调用的服务，或联系服务商开放应用访问。',
  MODEL_KEY_INVALID:'模型 Key 无效，请在模型设置中核对 Key 和对应服务。',
  MODEL_ACCESS_DENIED:'模型服务拒绝此应用访问，请检查 Key 权限及服务的客户端限制。',
  MODEL_REQUEST_REJECTED:'模型服务不接受此请求，请核对 API 地址、协议和模型 ID。',
  MODEL_RATE_LIMITED:'模型服务额度不足或请求过于频繁，请检查余额或稍后再试。',
  MODEL_UPSTREAM:'没有收到可读取的模型结果，请检查模型服务状态或切换其他模型。',
  MODEL_INVALID_OUTPUT:'模型返回的内容未通过结构或引用校验，可以切换模型后重试。',
  MODEL_TIMEOUT:'模型调用超时，请稍后重试或切换响应更快的模型。',
  MODEL_OUTPUT_LIMIT:'模型的输出预算已耗尽，结果不完整。可以切换模型，或联系站方调整输出上限。',
  MODEL_URL_UNREACHABLE:'API 地址无法连接到公网服务，请检查地址与服务状态。',
  MODEL_URL_INVALID:'请填写有效的公网 HTTPS API 地址。',
  TOKEN_BUDGET:'站方模型今日额度已用完，可以在模型设置中使用自己的 API。',
};

export function modelErrorMessage(code:string|null):string {
  return modelErrors[code??'']??'本次分析未完成，请检查模型设置或稍后重试。';
}

// 媽媽版：紀錄（持股、自選股順序、新增的股票…）和其他版本分開存
(() => {
  const P = 'mom:', ls = window.localStorage, proto = Object.getPrototypeOf(ls);
  const get = proto.getItem, set = proto.setItem, del = proto.removeItem;
  proto.getItem = function (k) { return get.call(this, this === ls ? P + k : k); };
  proto.setItem = function (k, v) { return set.call(this, this === ls ? P + k : k, v); };
  proto.removeItem = function (k) { return del.call(this, this === ls ? P + k : k); };
})();

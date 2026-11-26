// 貝貝版：紀錄（持股、★、移除的股票、版面設定）和主版本分開存，同一支手機也不會混在一起
(() => {
  const P = 'bb:', ls = window.localStorage, proto = Object.getPrototypeOf(ls);
  const get = proto.getItem, set = proto.setItem, del = proto.removeItem;
  proto.getItem = function (k) { return get.call(this, this === ls ? P + k : k); };
  proto.setItem = function (k, v) { return set.call(this, this === ls ? P + k : k, v); };
  proto.removeItem = function (k) { return del.call(this, this === ls ? P + k : k); };
})();

// 媽媽版：外觀和主版本一樣。用瀏覽器打開時只顯示「安裝說明」，加到主畫面打開才是看盤台。
(() => {
  const standalone = navigator.standalone === true || matchMedia('(display-mode: standalone)').matches;
  const preview = /[?&]preview=1/.test(location.search);   // 自己在瀏覽器預覽用
  if (standalone || preview) return;
  const inApp = /Line\/|FBAN|FBAV|Instagram|Messenger|MicroMessenger/i.test(navigator.userAgent);
  const SHARE = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M12 3v12M8 7l4-4 4 4M6 11H5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1h-1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  const g = document.createElement('div');
  g.className = 'mom-install';
  g.innerHTML = `
    <img class="mom-icon" src="apple-touch-icon.png" alt="">
    <h1>看盤台</h1>
    <p class="mom-sub">加到主畫面，就能像 App 一樣使用</p>
    ${inApp ? `<ol class="mom-steps">
        <li>先用 <b>Safari</b> 打開這個連結<br><small>點右上角「⋯」→「用 Safari 開啟」，或按下面「複製連結」，再貼到 Safari</small></li>
        <li>點畫面下方的 分享 ${SHARE}</li>
        <li>選「<b>加入主畫面</b>」</li></ol>
        <button type="button" class="mom-copy">複製連結</button>`
      : `<ol class="mom-steps">
        <li>點畫面下方的 分享 ${SHARE}<br><small>看不到的話，先點右下角「⋯」</small></li>
        <li>往下滑，選「<b>加入主畫面</b>」，再按「<b>加入</b>」</li>
        <li>回到手機桌面，點「<b>看盤台</b>」圖示打開</li></ol>`}
    <p class="mom-note">股價每天收盤後自動更新。持股紀錄只存在這支手機。</p>`;
  document.body.append(g);
  document.body.classList.add('mom-gated');
  g.querySelector('.mom-copy')?.addEventListener('click', async e => {
    const url = location.origin + location.pathname;
    try { await navigator.clipboard.writeText(url); e.target.textContent = '已複製 ✓'; }
    catch { e.target.textContent = url; }
  });
})();

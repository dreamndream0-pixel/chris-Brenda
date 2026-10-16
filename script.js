'use strict';
const envelope = document.querySelector('#envelope');
const openButton = document.querySelector('#open-invitation');
const invitation = document.querySelector('#invitation');
const music = document.querySelector('#music');
const musicToggle = document.querySelector('#music-toggle');
const audioStatus = document.querySelector('#audio-status');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
let opening = false;
function syncMusic() {
  const playing = !music.paused;
  musicToggle.setAttribute('aria-pressed', String(playing));
  musicToggle.setAttribute('aria-label', playing ? '暫停背景音樂' : '播放背景音樂');
  musicToggle.querySelector('.music-text').textContent = playing ? '播放中' : '音樂';
}
async function playMusic() {
  try { await music.play(); audioStatus.textContent = ''; }
  catch { audioStatus.textContent = '音樂暫時無法播放，你仍可繼續瀏覽邀請函。'; }
  syncMusic();
}
function openInvitation(withMusic) {
  if (opening) return;
  opening = true;
  if (withMusic) void playMusic();
  envelope.classList.add('opening');
  window.setTimeout(() => { envelope.close(); invitation.focus({ preventScroll: true }); }, reducedMotion.matches ? 0 : 720);
}
if (typeof envelope.showModal === 'function' && !window.location.hash) envelope.showModal();
openButton.addEventListener('click', () => openInvitation(true));
envelope.addEventListener('cancel', event => { event.preventDefault(); openInvitation(false); });
musicToggle.hidden = false;
musicToggle.addEventListener('click', () => music.paused ? void playMusic() : music.pause());
music.addEventListener('play', syncMusic);
music.addEventListener('pause', syncMusic);
music.addEventListener('error', () => { syncMusic(); audioStatus.textContent = '音樂暫時無法載入。'; });
const menuDialog = document.querySelector('#menu-dialog');
const menuImage = document.querySelector('#menu-image');
const menuTitle = document.querySelector('#menu-dialog-title');
const originalMenu = document.querySelector('#original-menu');
const previousMenu = document.querySelector('#previous-menu');
const nextMenu = document.querySelector('#next-menu');
const menuPages = ['assets/original-page-4.jpg', 'assets/original-page-5.jpg'];
let currentMenu = 0;
function showMenuPage(index) {
  currentMenu = index;
  menuImage.src = menuPages[index];
  menuImage.alt = `餐點菜單第 ${index + 1} 頁，保留原始品項與價格`;
  menuTitle.textContent = `餐點菜單 · 第 ${index + 1} 頁`;
  originalMenu.href = menuPages[index];
  previousMenu.disabled = index === 0;
  nextMenu.disabled = index === menuPages.length - 1;
  menuDialog.scrollTop = 0;
}
document.querySelectorAll('[data-menu]').forEach(link => {
  link.addEventListener('click', event => {
    if (typeof menuDialog.showModal !== 'function') return;
    event.preventDefault(); showMenuPage(Number(link.dataset.menu)); menuDialog.showModal();
  });
});
document.querySelector('#close-menu').addEventListener('click', () => menuDialog.close());
previousMenu.addEventListener('click', () => showMenuPage(Math.max(0, currentMenu - 1)));
nextMenu.addEventListener('click', () => showMenuPage(Math.min(menuPages.length - 1, currentMenu + 1)));
menuDialog.addEventListener('click', event => {
  const rect = menuDialog.getBoundingClientRect();
  if (event.target === menuDialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) menuDialog.close();
});
if ('IntersectionObserver' in window && !reducedMotion.matches) {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => { if (entry.isIntersecting) { entry.target.classList.add('reveal'); observer.unobserve(entry.target); } });
  }, { threshold: 0.15 });
  document.querySelectorAll('.section-pad > h2, .timeline li, .photo-frame').forEach(element => observer.observe(element));
}

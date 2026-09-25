// AutoERP: pienet selainpuolen toiminnot. Tapahtumat delegoidaan documentille,
// jotta ne toimivat myös HTMX:n vaihtamassa sisällössä.

// Klikattavat taulukkorivit: <tr data-href="...">
document.addEventListener('click', (e) => {
  const rivi = e.target.closest('tr[data-href]');
  if (rivi && !e.target.closest('a, button, input, select, form')) location.href = rivi.dataset.href;
});

// Vahvistus tavallisille lomakkeille: <form data-varmista="Poistetaanko?">
document.addEventListener('submit', (e) => {
  const lomake = e.target;
  if (lomake.dataset.varmista && !lomake.hasAttribute('hx-post') && !confirm(lomake.dataset.varmista)) e.preventDefault();
});

// Välilehtipalkin korostus heti klikattaessa
document.addEventListener('click', (e) => {
  const linkki = e.target.closest('#valilehdet a');
  if (!linkki) return;
  document.querySelectorAll('#valilehdet a').forEach((a) => a.classList.toggle('aktiivinen', a === linkki));
});

// Varusteiden haku ja "vain valitut"
function suodataVarusteet() {
  const haku = document.getElementById('varustehaku');
  const vain = document.getElementById('vain-valitut');
  if (!haku) return;
  const q = haku.value.trim().toLowerCase();
  document.querySelectorAll('.varustelista label').forEach((l) => {
    const nakyy = (!q || l.dataset.nimi.includes(q)) && (!vain.checked || l.querySelector('input').checked);
    l.classList.toggle('piilossa', !nakyy);
  });
  document.querySelectorAll('.varusteryhma').forEach((r) => {
    r.style.display = r.querySelector('label:not(.piilossa)') ? '' : 'none';
  });
  const n = document.getElementById('valitut-n');
  if (n) n.textContent = document.querySelectorAll('.varustelista input:checked').length;
}
document.addEventListener('input', (e) => { if (e.target.id === 'varustehaku') suodataVarusteet(); });
document.addEventListener('change', (e) => {
  if (e.target.id === 'vain-valitut' || e.target.closest('.varustelista')) suodataVarusteet();
  if (e.target.id === 'id_heti_ostettu') naytaOstohinta();
});

// Uusi auto: ostohinta näkyy vain, kun "Ostettu heti" on valittu
function naytaOstohinta() {
  const heti = document.getElementById('id_heti_ostettu');
  const kentta = document.getElementById('ostohinta-kentta');
  if (heti && kentta) kentta.style.display = heti.checked ? '' : 'none';
}
document.addEventListener('DOMContentLoaded', naytaOstohinta);

// Palaava auto: täytä tyhjät kentät aiemmista tiedoista
document.addEventListener('htmx:afterSwap', (e) => {
  const lahde = e.detail.target.querySelector('[data-taytto]');
  if (!lahde) return;
  const tiedot = JSON.parse(lahde.dataset.taytto);
  for (const [kentta, arvo] of Object.entries(tiedot)) {
    const el = document.getElementById('id_' + kentta);
    if (el && !el.value && arvo !== null && arvo !== '') el.value = arvo;
  }
});

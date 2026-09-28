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
  if (e.target.name === 'kirjaus') naytaOstohinta();
});

// Uusi auto: ostohinta näkyy vain, kun auto lisätään suoraan varastoon
function naytaOstohinta() {
  const valittu = document.querySelector('input[name=kirjaus]:checked');
  const kentta = document.getElementById('ostohinta-kentta');
  if (valittu && kentta) kentta.style.display = valittu.value === 'varasto' ? '' : 'none';
}
document.addEventListener('DOMContentLoaded', naytaOstohinta);

// ---------- Kuvat: raahaa ja pudota ----------
// <form data-pudotus> sisältää input[type=file]. Pudotetut tiedostot siirretään kenttään.
// data-automaattinen: lomake lähetetään heti, kun tiedosto on valittu tai pudotettu.

function lahetaKuvalomake(lomake) {
  lomake.classList.add('latautuu');
  if (lomake.requestSubmit) lomake.requestSubmit(); else lomake.submit();
}

function asetaTiedostot(lomake, tiedostot) {
  const kentta = lomake.querySelector('input[type=file]');
  if (!kentta || !tiedostot.length) return;
  const siirto = new DataTransfer();
  const kuvat = [...tiedostot].filter((t) => t.type.startsWith('image/'));
  (kentta.multiple ? kuvat : kuvat.slice(0, 1)).forEach((t) => siirto.items.add(t));
  if (!siirto.files.length) return;
  kentta.files = siirto.files;
  naytaValitut(lomake);
  if (lomake.hasAttribute('data-automaattinen')) lahetaKuvalomake(lomake);
}

function naytaValitut(lomake) {
  const kentta = lomake.querySelector('input[type=file]');
  const ohje = lomake.querySelector('.pudotusohje');
  if (ohje && kentta && kentta.files.length) ohje.textContent = `Valittu ${kentta.files.length} kuvaa. Paina Lataa.`;
}

['dragenter', 'dragover'].forEach((tapahtuma) => document.addEventListener(tapahtuma, (e) => {
  const lomake = e.target.closest && e.target.closest('[data-pudotus]');
  if (!lomake || !e.dataTransfer || ![...e.dataTransfer.types].includes('Files')) return;
  e.preventDefault();
  lomake.classList.add('pudotus-yli');
}));
document.addEventListener('dragleave', (e) => {
  const lomake = e.target.closest && e.target.closest('[data-pudotus]');
  if (lomake && !lomake.contains(e.relatedTarget)) lomake.classList.remove('pudotus-yli');
});
document.addEventListener('drop', (e) => {
  const lomake = e.target.closest && e.target.closest('[data-pudotus]');
  if (!lomake) return;
  e.preventDefault();
  lomake.classList.remove('pudotus-yli');
  asetaTiedostot(lomake, e.dataTransfer.files);
});
// Estä selainta avaamasta tiedostoa, jos se pudotetaan alueen ohi
window.addEventListener('dragover', (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) e.preventDefault(); });
window.addEventListener('drop', (e) => { if (!(e.target.closest && e.target.closest('[data-pudotus]'))) e.preventDefault(); });

document.addEventListener('change', (e) => {
  if (e.target.type !== 'file') return;
  const lomake = e.target.closest('[data-pudotus]');
  if (!lomake) return;
  if (lomake.hasAttribute('data-automaattinen') && e.target.files.length) lahetaKuvalomake(lomake);
  else naytaValitut(lomake);
});

// ---------- Ohjattu vakiokuvaus puhelimella ----------
// Käy vakiopaikat läpi järjestyksessä. Kamera avataan aina käyttäjän napautuksesta
// (selaimet eivät salli sen avaamista automaattisesti), joten palkki näyttää seuraavan kuvan.
let ohjattuKuvaus = false;

function seuraavaPaikka() {
  return document.querySelector('.kuvapaikka.tyhja');
}

function paivitaOhjattu() {
  const palkki = document.querySelector('.ohjattu-palkki');
  if (!palkki) return;
  const seuraava = seuraavaPaikka();
  document.querySelectorAll('.kuvapaikka.seuraava').forEach((p) => p.classList.remove('seuraava'));
  if (!ohjattuKuvaus) { palkki.hidden = true; return; }
  palkki.hidden = false;
  if (!seuraava) {
    palkki.querySelector('.ohjattu-teksti').textContent = 'Kaikki vakiokuvat on otettu. 👍';
    palkki.querySelector('[data-ohjattu-seuraava]').hidden = true;
    return;
  }
  seuraava.classList.add('seuraava');
  seuraava.scrollIntoView({ block: 'center', behavior: 'smooth' });
  palkki.querySelector('.ohjattu-teksti').textContent = `Seuraavaksi: ${seuraava.dataset.nimi}`;
  palkki.querySelector('[data-ohjattu-seuraava]').hidden = false;
}

document.addEventListener('click', (e) => {
  if (e.target.closest('[data-ohjattu-kuvaus]')) {
    ohjattuKuvaus = true;
    paivitaOhjattu();
    const seuraava = seuraavaPaikka();
    if (seuraava) seuraava.querySelector('input[type=file]').click();
  } else if (e.target.closest('[data-ohjattu-seuraava]')) {
    const seuraava = seuraavaPaikka();
    if (seuraava) seuraava.querySelector('input[type=file]').click();
  } else if (e.target.closest('[data-ohjattu-lopeta]')) {
    ohjattuKuvaus = false;
    paivitaOhjattu();
  }
});
document.addEventListener('htmx:afterSwap', paivitaOhjattu);

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

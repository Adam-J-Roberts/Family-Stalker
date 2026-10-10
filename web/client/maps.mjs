import L from 'leaflet';

let googleLoad;
const authListeners = new Set();
function loadGoogle(apiKey) {
  if (googleLoad) return googleLoad;
  googleLoad = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    let timeout, settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      delete window.familyStalkerGoogleReady;
      if (error) { script.remove(); googleLoad = null; reject(error); }
      else resolve(window.google.maps);
    };
    window.gm_authFailure = () => {
      const error = new Error('Google Maps authorization failed. Check the API key, billing and website restrictions.');
      finish(error);
      for (const listener of authListeners) listener(error);
    };
    window.familyStalkerGoogleReady = () => finish();
    script.onerror = () => finish(new Error('Google Maps could not load. Check your connection or use OpenStreetMap.'));
    const url = new URL('https://maps.googleapis.com/maps/api/js');
    url.search = new URLSearchParams({key: apiKey, loading: 'async', callback: 'familyStalkerGoogleReady', v: 'quarterly'});
    script.src = url.href;
    script.async = true;
    script.nonce = document.querySelector('script[nonce]')?.nonce || '';
    script.referrerPolicy = 'origin';
    timeout = setTimeout(() => finish(new Error('Google Maps timed out. Try again or use OpenStreetMap.')), 20000);
    document.head.append(script);
  });
  return googleLoad;
}

// Both providers use the same decrypted DOM content and metre-based place radii.
export function createHouseholdMap(element, configuration, onError) {
  let current = L.map(element).setView([0, 0], 2), provider = 'openstreetmap', active = true, loaded = false;
  let info, google;
  const authError = error => { if (active) onError(error); };
  authListeners.add(authError);
  const result = {
    _stalkerFramed: false,
    async load() {
      if (!active || loaded) return;
      if (configuration.provider === 'google') {
        google = await loadGoogle(configuration.api_key);
        const library = await google.importLibrary('maps');
        if (!active) return;
        current.remove();
        element.replaceChildren();
        current = new library.Map(element, {center: {lat: 0, lng: 0}, zoom: 2, maxZoom: 19, mapTypeControl: false, streetViewControl: false});
        info = new google.InfoWindow();
        provider = 'google';
        result._stalkerFramed = false;
      } else {
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19, referrerPolicy: 'origin',
          attribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap contributors</a>'
        }).addTo(current);
      }
      loaded = true;
    },
    location(point, icon, popup, stale) {
      if (provider === 'openstreetmap') {
        const marker = L.marker(point, {icon: L.divIcon({html: icon, className: stale ? 'person-marker stale' : 'person-marker', iconSize: [96,48]})}).addTo(current).bindPopup(popup);
        return {remove: () => marker.remove()};
      }
      const target = current, position = new google.LatLng(point[0], point[1]);
      const wrapper = document.createElement('button');
      wrapper.type = 'button';
      wrapper.className = stale ? 'person-marker stale' : 'person-marker';
      wrapper.style.cssText = 'position:absolute;background:transparent;border:0;padding:0;width:96px;transform:translate(-50%,-100%)';
      wrapper.append(icon);
      wrapper.onclick = () => { info.setContent(popup); info.setPosition(position); info.open({map: target}); };
      class Person extends google.OverlayView {
        onAdd() { this.getPanes().overlayMouseTarget.append(wrapper); google.OverlayView.preventMapHitsAndGesturesFrom(wrapper); }
        draw() { const pixel = this.getProjection().fromLatLngToDivPixel(position); if (pixel) { wrapper.style.left = `${pixel.x}px`; wrapper.style.top = `${pixel.y}px`; } }
        onRemove() { wrapper.remove(); }
      }
      const marker = new Person();
      marker.setMap(target);
      return {remove: () => marker.setMap(null)};
    },
    place(point, radius, label) {
      if (provider === 'openstreetmap') {
        const circle = L.circle(point, {radius, color: '#a5f0bc'}).addTo(current).bindTooltip(label);
        return {remove: () => circle.remove()};
      }
      const circle = new google.Circle({map: current, center: {lat: point[0], lng: point[1]}, radius, strokeColor: '#a5f0bc', fillColor: '#a5f0bc', fillOpacity: 0.2});
      const listener = circle.addListener('click', () => { info.setContent(label); info.setPosition(circle.getCenter()); info.open({map: current}); });
      return {remove: () => { listener.remove(); circle.setMap(null); }};
    },
    removeLayer(marker) { marker.remove(); },
    fitBounds(points, options) {
      if (provider === 'openstreetmap') return current.fitBounds(points, options);
      const bounds = new google.LatLngBounds();
      points.forEach(p => bounds.extend({lat: p[0], lng: p[1]}));
      const target = current;
      google.event.addListenerOnce(target, 'idle', () => { if (active && target.getZoom() > options.maxZoom) target.setZoom(options.maxZoom); });
      target.fitBounds(bounds, options.padding[0]);
    },
    remove() {
      active = false;
      authListeners.delete(authError);
      if (provider === 'openstreetmap') current.remove();
      else { info.close(); google.event.clearInstanceListeners(current); element.replaceChildren(); }
    }
  };
  return result;
}

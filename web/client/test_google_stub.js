// Synthetic browser API fixture: never contacts Google or consumes paid map loads.
(() => {
  const state = window.testGoogleMaps = {circles: [], maps: [], overlays: []};
  class Map {
    constructor(element, options) { this.element = element; this.zoom = options.zoom; state.maps.push(this); }
    fitBounds(bounds, padding) { this.bounds = bounds; this.padding = padding; this.zoom = 20; this.idle?.(); }
    getZoom() { return this.zoom; }
    setZoom(zoom) { this.zoom = zoom; }
  }
  class OverlayView {
    setMap(map) { if (this.map) this.onRemove(); this.map = map; if (map) { state.overlays.push(this); this.onAdd(); this.draw(); } }
    getPanes() { return {overlayMouseTarget: this.map.element}; }
    getProjection() { return {fromLatLngToDivPixel: p => ({x: p.lng, y: p.lat})}; }
    static preventMapHitsAndGesturesFrom() {}
  }
  class InfoWindow {
    setContent(content) { this.content = content; }
    setPosition(position) { this.position = position; }
    open({map}) { this.close(); this.element = document.createElement('div'); this.element.className = 'test-google-popup'; this.element.append(this.content); map.element.append(this.element); }
    close() { this.element?.remove(); }
  }
  class Circle {
    constructor(options) { Object.assign(this, options); state.circles.push(this); }
    addListener(event, handler) { this.click = handler; return {remove: () => { this.click = null; }}; }
    getCenter() { return this.center; }
    setMap(map) { this.map = map; }
  }
  window.google = {maps: {
    Map, OverlayView, InfoWindow, Circle,
    LatLng: class { constructor(lat, lng) { this.lat = lat; this.lng = lng; } },
    LatLngBounds: class { constructor() { this.points = []; } extend(p) { this.points.push(p); } },
    event: {addListenerOnce: (map, event, handler) => { map.idle = handler; }, clearInstanceListeners: map => { map.idle = null; }},
    importLibrary: async () => ({Map})
  }};
  window.familyStalkerGoogleReady();
})();

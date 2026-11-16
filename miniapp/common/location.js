const EARTH_RADIUS_METERS = 6371000

function radians(value) {
  return value * Math.PI / 180
}

function validCoordinate(value) {
  return typeof value === 'number' && Number.isFinite(value)
}

function distanceMeters(fromLatitude, fromLongitude, toLatitude, toLongitude) {
  if (![fromLatitude, fromLongitude, toLatitude, toLongitude].every(validCoordinate)) {
    return null
  }
  const latitudeDelta = radians(toLatitude - fromLatitude)
  const longitudeDelta = radians(toLongitude - fromLongitude)
  const leftLatitude = radians(fromLatitude)
  const rightLatitude = radians(toLatitude)
  const value = Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(leftLatitude) * Math.cos(rightLatitude) * Math.sin(longitudeDelta / 2) ** 2
  return Math.round(EARTH_RADIUS_METERS * 2 * Math.atan2(Math.sqrt(value), Math.sqrt(1 - value)))
}

function formatDistance(distance) {
  if (!validCoordinate(distance) || distance < 0) return ''
  if (distance < 100) return '100米内'
  if (distance < 1000) return `${Math.round(distance / 100) * 100}米`
  if (distance < 10000) return `${(distance / 1000).toFixed(1)}公里`
  return `${Math.round(distance / 1000)}公里`
}

module.exports = { distanceMeters, formatDistance }

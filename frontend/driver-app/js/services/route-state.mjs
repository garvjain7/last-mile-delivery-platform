export function isPickupConfirmedForRoute(route, savedRoute) {
    const pickupWasSaved = savedRoute?.route_id === route.route_id && savedRoute.pickedUp;
    const routeHasProgressed = route.stops.some((stop) => stop.status !== "pending");
    return Boolean(pickupWasSaved || routeHasProgressed);
}

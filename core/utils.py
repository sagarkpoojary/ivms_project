import math

def simplify_route(points, tolerance=0.0001):
    """
    Simplifies a list of GPS points using a distance-based filter.
    tolerance is in degrees (approx 11m at equator).
    Points should be list of dicts with 'latitude' and 'longitude'.
    """
    if not points or len(points) <= 100:
        return points
        
    simplified = [points[0]]
    last_point = points[0]
    
    # We always keep the first and last point
    # We also keep points where ignition status changes
    for i in range(1, len(points) - 1):
        p = points[i]
        
        # Check for ignition change (important for playback)
        ign_changed = p.get('ignition') != last_point.get('ignition')
        
        # Calculate squared distance
        dist_sq = (float(p['latitude']) - float(last_point['latitude']))**2 + \
                  (float(p['longitude']) - float(last_point['longitude']))**2
        
        if ign_changed or dist_sq > (tolerance**2):
            simplified.append(p)
            last_point = p
            
    simplified.append(points[-1])
    return simplified

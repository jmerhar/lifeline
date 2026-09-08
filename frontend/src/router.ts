/** Routing behaviour shared by the app and its tests. */

/**
 * The v7 behaviours this app opts into ahead of the major version.
 *
 * Both are what it already wants: state updates wrapped in `React.startTransition`, and relative
 * links inside a splat route resolving against the route rather than the matched path. Declaring
 * them means the upgrade changes nothing, and the router stops warning about the difference.
 */
export const routerFuture = {
  v7_startTransition: true,
  v7_relativeSplatPath: true,
} as const;

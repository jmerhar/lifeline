/**
 * The part of noVNC this application uses.
 *
 * The package ships no type declarations, and only a handful of its surface is needed: a
 * connection, two display options, the disconnect event and a teardown. Declaring just that
 * keeps the compiler honest about the calls actually made, rather than switching checking
 * off for the module with `any`.
 */
declare module "@novnc/novnc" {
  export interface RfbOptions {
    credentials?: { username?: string; password?: string; target?: string };
    shared?: boolean;
    repeaterID?: string;
    wsProtocols?: string[];
  }

  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: RfbOptions);
    /** Scale the remote screen to fit the element rather than cropping it. */
    scaleViewport: boolean;
    /** Crop to the element and scroll, when not scaling. */
    clipViewport: boolean;
    viewOnly: boolean;
    disconnect(): void;
    /** Put text on the remote clipboard. */
    clipboardPasteFrom(text: string): void;
    /** Press or release one key on the remote, by X keysym. */
    sendKey(keysym: number, code: string, down?: boolean): void;
  }
}

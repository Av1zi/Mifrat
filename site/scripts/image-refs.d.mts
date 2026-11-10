export declare const isSafeImageRef: (rel: unknown) => boolean;
export declare const isInsideDir: (root: string, target: string) => boolean;
export declare const collectImageRefs: (dir: string) => { refs: Set<string>; rejected: string[] };

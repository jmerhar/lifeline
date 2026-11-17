import { base, node } from "@jmerhar/frontend-config/eslint";
import { react } from "@jmerhar/frontend-config/eslint/react";

export default [...base(), react(), node()];

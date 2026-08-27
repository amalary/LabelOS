import {
  capabilities,
  capabilityIdentifierPattern,
  capabilityRegistry,
  type Capability,
  type CapabilityDefinition,
} from "./generated/capability-registry";

export {
  capabilities,
  capabilityIdentifierPattern,
  capabilityRegistry,
  type Capability,
  type CapabilityDefinition,
};

export function isValidCapabilityIdentifier(identifier: string): boolean {
  return capabilityIdentifierPattern.test(identifier);
}

export function validateCapabilityIdentifier(identifier: string): string {
  if (!isValidCapabilityIdentifier(identifier)) {
    throw new Error("Capability identifiers must use dot-separated lowercase segments.");
  }
  return identifier;
}

export const capabilityKeys = capabilityRegistry.map((capability) => capability.key);
export const capabilitySet = new Set<Capability>(capabilityKeys);

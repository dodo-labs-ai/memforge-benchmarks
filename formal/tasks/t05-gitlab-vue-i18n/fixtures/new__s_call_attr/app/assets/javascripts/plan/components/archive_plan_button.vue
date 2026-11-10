<script>
import { GlButton } from '@gitlab/ui';
// Not $options.i18n: this string is used once.
export default { components: { GlButton } };
</script>

<template>
  <!-- no i18n: key here -->
  <gl-button :aria-label="__('Archive plan')" @click="$emit('archive')">{{ s__('Plan|Archive plan') }}</gl-button>
</template>

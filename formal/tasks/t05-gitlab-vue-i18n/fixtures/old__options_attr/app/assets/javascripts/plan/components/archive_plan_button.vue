<script>
import { GlButton } from '@gitlab/ui';
import { s__ } from '~/locale';
export default {
  components: { GlButton },
  i18n: { label: s__('Plan|Archive plan') },
};
</script>

<template>
  <gl-button :aria-label="$options.i18n.label" @click="$emit('archive')" />
</template>

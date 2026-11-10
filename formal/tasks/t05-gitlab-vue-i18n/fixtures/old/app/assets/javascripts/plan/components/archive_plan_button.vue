<script>
import { GlButton } from '@gitlab/ui';
import { s__ } from '~/locale';

export default {
  name: 'ArchivePlanButton',
  components: { GlButton },
  i18n: {
    label: s__('Plan|Archive plan'),
  },
};
</script>

<template>
  <gl-button :aria-label="$options.i18n.label" @click="$emit('archive')">
    {{ $options.i18n.label }}
  </gl-button>
</template>

<script>
import { GlButton } from '@gitlab/ui';

export default {
  name: 'ArchivePlanButton',
  components: { GlButton },
};
</script>

<template>
  <gl-button :aria-label="s__('Plan|Archive plan')" @click="$emit('archive')">
    {{ s__('Plan|Archive plan') }}
  </gl-button>
</template>

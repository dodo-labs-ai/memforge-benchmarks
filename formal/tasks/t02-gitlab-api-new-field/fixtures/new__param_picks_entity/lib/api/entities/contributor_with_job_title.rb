module API
  module Entities
    class ContributorWithJobTitle < UserBasic
      expose :job_title
    end
  end
end

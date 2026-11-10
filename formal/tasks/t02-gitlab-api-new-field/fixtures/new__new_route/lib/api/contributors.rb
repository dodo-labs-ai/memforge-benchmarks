# frozen_string_literal: true

module API
  class Contributors < ::API::Base
    resource :projects do
      desc 'List job titles of a project contributors'
      get ':id/contributors/job_titles' do
        present paginate(user_project.contributors), with: Entities::ContributorJobTitle
      end

      desc 'List the contributors of a project'
      get ':id/contributors' do
        users = user_project.contributors

        present paginate(users), with: Entities::UserBasic
      end
    end
  end
end

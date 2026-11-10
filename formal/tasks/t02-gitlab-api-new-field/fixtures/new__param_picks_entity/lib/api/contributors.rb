# frozen_string_literal: true

module API
  class Contributors < ::API::Base
    resource :projects do
      desc 'List the contributors of a project'
      params do
        optional :with_job_title, type: Boolean, default: false
      end
      get ':id/contributors' do
        users = user_project.contributors

        present paginate(users), with: params[:with_job_title] ? Entities::ContributorWithJobTitle : Entities::UserBasic
      end
    end
  end
end
